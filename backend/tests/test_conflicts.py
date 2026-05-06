"""Resource-conflict detection tests for U6.

Covers:

* In-process ``Scheduler.check_for_conflicts`` against hand-built ``Experiment``
  instances (pure-function semantics, no app context required).
* Edge cases the plan calls out: zero-duration steps, ``None`` /``""``
  resources, dependency-serialized chains.
* Round-trip via ``GET /api/experiments/<id>/conflicts`` matches the in-process
  call exactly. The route layer should add no new policy beyond view-permission
  gating.
"""
from datetime import datetime, timedelta

from models import Condition, Experiment, Step, StepType
from scheduler import Scheduler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_step(name, resource, start, duration_minutes, step_type=StepType.FIXED_DURATION):
    """Build a ``Step`` with a pre-populated scheduled window.

    The conflict detector reads ``scheduled_start_time`` /
    ``scheduled_end_time`` directly -- we don't need to run the full scheduler
    here. That keeps the assertions about the algorithm itself, not about how
    initial scheduling happens to lay things out.
    """
    duration = timedelta(minutes=duration_minutes)
    step = Step(name=name, duration=duration, step_type=step_type, resource_needed=resource)
    step.scheduled_start_time = start
    step.scheduled_end_time = start + duration
    return step


def _experiment_with(steps):
    exp = Experiment(name="ConflictTest")
    exp.owner = "alice"
    exp.shared_with = {}
    for s in steps:
        exp.add_step(s)
    return exp


# ---------------------------------------------------------------------------
# 1. Two FIXED_DURATION steps overlapping on the same resource -> one conflict.
# ---------------------------------------------------------------------------
def test_overlap_on_same_resource_flags_one_conflict():
    """14:00-15:00 and 14:30-15:30 on "microscope" -> overlap_seconds == 1800."""
    base = datetime(2026, 1, 1, 14, 0, 0)
    a = _make_step("A", "microscope", base, duration_minutes=60)
    b = _make_step("B", "microscope", base + timedelta(minutes=30), duration_minutes=60)
    exp = _experiment_with([a, b])

    conflicts = Scheduler.check_for_conflicts(exp)

    assert len(conflicts) == 1
    c = conflicts[0]
    assert c["resource"] == "microscope"
    assert c["overlap_seconds"] == 1800  # 30-minute overlap
    # Step IDs should be the actual UUIDs from the dataclass instances.
    assert {c["step_a"], c["step_b"]} == {a.id, b.id}
    # Names are included so the frontend renders without a second lookup.
    assert {c["step_a_name"], c["step_b_name"]} == {"A", "B"}


# ---------------------------------------------------------------------------
# 2. Different resources at the same time -> no conflict.
# ---------------------------------------------------------------------------
def test_different_resources_no_conflict():
    base = datetime(2026, 1, 1, 14, 0, 0)
    a = _make_step("A", "microscope", base, duration_minutes=60)
    b = _make_step("B", "centrifuge", base, duration_minutes=60)
    exp = _experiment_with([a, b])

    assert Scheduler.check_for_conflicts(exp) == []


# ---------------------------------------------------------------------------
# 3. Zero-duration steps don't crash and are skipped from results.
# ---------------------------------------------------------------------------
def test_zero_duration_step_is_skipped_without_crashing():
    """A step with start == end can't actually overlap anything (half-open
    intervals); ensure we don't crash and don't emit a phantom conflict."""
    base = datetime(2026, 1, 1, 14, 0, 0)
    zero = _make_step("Z", "microscope", base, duration_minutes=0)
    other = _make_step("O", "microscope", base, duration_minutes=60)
    exp = _experiment_with([zero, other])

    conflicts = Scheduler.check_for_conflicts(exp)
    # Zero-duration's [start, start) overlaps nothing under half-open
    # semantics. The algorithm must not produce a conflict involving Z.
    assert all(zero.id not in (c["step_a"], c["step_b"]) for c in conflicts)


# ---------------------------------------------------------------------------
# 4. Dependency-serialized chains produce no spurious conflicts.
# ---------------------------------------------------------------------------
def test_dependency_chained_steps_no_conflict():
    """A->B chain on the same resource where B starts exactly when A ends
    must NOT produce a conflict. Half-open intervals: ``a.end == b.start``
    is the boundary case the plan explicitly relies on."""
    base = datetime(2026, 1, 1, 14, 0, 0)
    a = _make_step("A", "microscope", base, duration_minutes=30)
    b = _make_step("B", "microscope", base + timedelta(minutes=30), duration_minutes=30)
    # Chain B onto A's completion.
    b.dependencies = [a.id]
    exp = _experiment_with([a, b])

    assert Scheduler.check_for_conflicts(exp) == []


# ---------------------------------------------------------------------------
# 5. None / empty-string resources are skipped.
# ---------------------------------------------------------------------------
def test_none_or_empty_resource_skipped():
    base = datetime(2026, 1, 1, 14, 0, 0)
    # Build steps WITHOUT going through Step.__init__'s default-resource
    # branch (which would set "user_attention" on TASK steps). The algorithm
    # must skip steps whose resource is None or "".
    none_step = _make_step("N", None, base, duration_minutes=60, step_type=StepType.FIXED_DURATION)
    none_step.resource_needed = None  # belt-and-suspenders for FIXED_DURATION default
    empty_step = _make_step("E", "", base, duration_minutes=60, step_type=StepType.FIXED_DURATION)
    empty_step.resource_needed = ""
    exp = _experiment_with([none_step, empty_step])

    assert Scheduler.check_for_conflicts(exp) == []


# ---------------------------------------------------------------------------
# 6. Round-trip via the API matches the in-process call.
# ---------------------------------------------------------------------------
def test_conflicts_api_round_trip(client, auth_headers):
    """``GET /api/experiments/<id>/conflicts`` returns exactly what
    ``Scheduler.check_for_conflicts`` would return for the same experiment.

    We create an experiment with two overlapping resource users, then compare
    the route's JSON output to the in-process function call (over the same
    in-memory experiment object). They must be byte-for-byte equivalent so a
    consumer can use either source interchangeably.
    """
    payload = {
        "name": "ConflictRoundTrip",
        "description": "two steps fight for the microscope",
        "steps": [
            {
                "name": "A",
                "step_type": "fixed_duration",
                "duration_seconds": 3600,
                "dependencies": [],
                "resource_required": "microscope",
            },
            {
                "name": "B",
                "step_type": "fixed_duration",
                "duration_seconds": 3600,
                "dependencies": [],
                "resource_required": "microscope",
            },
        ],
    }
    r = client.post("/api/experiments", headers=auth_headers, json=payload)
    assert r.status_code == 201, r.get_json()
    exp_id = r.get_json()["id"]

    # Pull the in-memory experiment object so we can compare against the
    # in-process function. Tests run inside the test client which already
    # owns an app context (the fixture sets TESTING but doesn't push a
    # context), so wrap the lookup in one.
    import main as main_module
    with main_module.app.app_context():
        exp = main_module.scheduler.experiments.get(exp_id)
        in_process = Scheduler.check_for_conflicts(exp)

    r = client.get(f"/api/experiments/{exp_id}/conflicts", headers=auth_headers)
    assert r.status_code == 200, r.get_json()
    over_wire = r.get_json()

    # Order matters: the algorithm sorts by start within a resource group,
    # so two equivalent calls produce the same ordering.
    assert over_wire == in_process
    # Sanity: the create call placed both steps at ``now`` so they overlap
    # for the full hour.
    assert len(over_wire) == 1
    assert over_wire[0]["resource"] == "microscope"
    assert over_wire[0]["overlap_seconds"] == 60 * 60


def test_conflicts_route_unrelated_user_gets_404(client, auth_headers, second_user_headers):
    """Existence-privacy: a user without view permission gets 404, not 403.
    Mirrors ``get_experiment`` policy so attackers can't enumerate IDs.
    """
    payload = {
        "name": "PrivateConflictExp",
        "description": "",
        "steps": [
            {"name": "A", "step_type": "fixed_duration", "duration_seconds": 300, "dependencies": [], "resource_required": "x"},
        ],
    }
    r = client.post("/api/experiments", headers=auth_headers, json=payload)
    assert r.status_code == 201
    exp_id = r.get_json()["id"]

    r = client.get(f"/api/experiments/{exp_id}/conflicts", headers=second_user_headers)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 7. U2: conflict payload includes condition labels (id + name) per side.
# ---------------------------------------------------------------------------
def test_conflict_payload_includes_condition_labels():
    """`Covers AE1.` Two Conditions, one shared microscope, overlapping
    schedule -> the conflict carries condition_a_id/name and condition_b_id/name
    populated from the experiment's Condition cache.
    """
    base = datetime(2026, 1, 1, 14, 0, 0)
    a = _make_step("Image A", "microscope", base, duration_minutes=30)
    b = _make_step(
        "Image B", "microscope", base + timedelta(minutes=10), duration_minutes=30
    )
    exp = _experiment_with([a, b])

    cond_a = Condition(
        experiment_id=exp.id, name="Condition A", color="coral", order_index=0, id="condA"
    )
    cond_b = Condition(
        experiment_id=exp.id, name="Condition B", color="teal", order_index=1, id="condB"
    )
    exp.add_condition(cond_a)
    exp.add_condition(cond_b)
    a.condition_id = cond_a.id
    b.condition_id = cond_b.id

    conflicts = Scheduler.check_for_conflicts(exp)
    assert len(conflicts) == 1
    c = conflicts[0]

    # Pre-existing fields untouched.
    assert c["resource"] == "microscope"
    assert c["overlap_seconds"] == 20 * 60
    assert {c["step_a"], c["step_b"]} == {a.id, b.id}
    assert {c["step_a_name"], c["step_b_name"]} == {"Image A", "Image B"}

    # New U2 fields. Pairing is by step_a/step_b ordering (which the algorithm
    # decides via start-time sort). We just need the *pair* of (id, name) on
    # each side to match the *pair* on the corresponding step.
    a_side = (c["condition_a_id"], c["condition_a_name"])
    b_side = (c["condition_b_id"], c["condition_b_name"])
    if c["step_a"] == a.id:
        assert a_side == ("condA", "Condition A")
        assert b_side == ("condB", "Condition B")
    else:
        assert a_side == ("condB", "Condition B")
        assert b_side == ("condA", "Condition A")


# ---------------------------------------------------------------------------
# 8. U2: a step pointing at a condition_id missing from experiment.conditions
# (data corruption / mid-edit race) does NOT crash; we emit "Unknown".
# ---------------------------------------------------------------------------
def test_conflict_payload_handles_missing_condition_gracefully():
    """Defensive: a step references a condition that isn't in the cache.

    The detector must not raise; instead it reports the offending side's
    condition_*_name as "Unknown" and condition_*_id as the step's raw
    condition_id (which may be a stale FK or None).
    """
    base = datetime(2026, 1, 1, 14, 0, 0)
    a = _make_step("A", "microscope", base, duration_minutes=30)
    b = _make_step("B", "microscope", base + timedelta(minutes=10), duration_minutes=30)
    exp = _experiment_with([a, b])

    # Only register a condition for A. B points at a stale condition_id with
    # no corresponding Condition object.
    cond_a = Condition(experiment_id=exp.id, name="Condition A", id="condA")
    exp.add_condition(cond_a)
    a.condition_id = cond_a.id
    b.condition_id = "ghost-condition-id"  # never registered on the experiment

    conflicts = Scheduler.check_for_conflicts(exp)
    assert len(conflicts) == 1
    c = conflicts[0]

    # Determine which side is which by matching step IDs.
    if c["step_a"] == a.id:
        a_id_field, a_name_field = "condition_a_id", "condition_a_name"
        b_id_field, b_name_field = "condition_b_id", "condition_b_name"
    else:
        a_id_field, a_name_field = "condition_b_id", "condition_b_name"
        b_id_field, b_name_field = "condition_a_id", "condition_a_name"

    assert c[a_id_field] == "condA"
    assert c[a_name_field] == "Condition A"
    # The unregistered condition_id is preserved verbatim; the name is "Unknown".
    assert c[b_id_field] == "ghost-condition-id"
    assert c[b_name_field] == "Unknown"


# ---------------------------------------------------------------------------
# 9. U2: a step with condition_id=None doesn't crash; both id and name fall
# back gracefully.
# ---------------------------------------------------------------------------
def test_conflict_payload_handles_null_condition_id():
    """A step with no condition_id at all (pre-backfill / direct dataclass
    construction) reports condition_*_name = "Unknown", condition_*_id = None.
    """
    base = datetime(2026, 1, 1, 14, 0, 0)
    a = _make_step("A", "microscope", base, duration_minutes=30)
    b = _make_step("B", "microscope", base + timedelta(minutes=10), duration_minutes=30)
    exp = _experiment_with([a, b])
    # Neither step has a condition_id; experiment.conditions is empty.
    a.condition_id = None
    b.condition_id = None

    conflicts = Scheduler.check_for_conflicts(exp)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c["condition_a_id"] is None
    assert c["condition_b_id"] is None
    assert c["condition_a_name"] == "Unknown"
    assert c["condition_b_name"] == "Unknown"


def test_update_experiment_response_includes_conflicts(client, auth_headers):
    """PUT /api/experiments/<id> attaches the conflict list to the response so
    the Designer can surface it without an extra fetch (U6 contract).
    Notification emission for these is U7's responsibility -- this just
    validates the payload shape."""
    create_payload = {
        "name": "DesignerConflict",
        "description": "",
        "steps": [
            {"name": "A", "step_type": "fixed_duration", "duration_seconds": 3600, "dependencies": [], "resource_required": "microscope"},
        ],
    }
    r = client.post("/api/experiments", headers=auth_headers, json=create_payload)
    assert r.status_code == 201
    created = r.get_json()
    exp_id = created["id"]

    # Add a second step that fights the first on the same resource. We send
    # IDs so the upsert path keeps the original step instead of recreating it.
    update_payload = {
        "name": created["name"],
        "description": created["description"],
        "steps": [
            {
                "id": created["steps"][0]["id"],
                "name": created["steps"][0]["name"],
                "step_type": created["steps"][0]["step_type"],
                "duration_seconds": created["steps"][0]["duration_seconds"],
                "dependencies": [],
                "resource_required": "microscope",
            },
            {
                "name": "B",
                "step_type": "fixed_duration",
                "duration_seconds": 3600,
                "dependencies": [],
                "resource_required": "microscope",
            },
        ],
    }
    r = client.put(f"/api/experiments/{exp_id}", headers=auth_headers, json=update_payload)
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert "conflicts" in body
    assert len(body["conflicts"]) == 1
    assert body["conflicts"][0]["resource"] == "microscope"
