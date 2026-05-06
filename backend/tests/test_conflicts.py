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

from models import Experiment, Step, StepType
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
                "type": "fixed_duration",
                "duration": 60,
                "dependencies": [],
                "resourceNeeded": "microscope",
            },
            {
                "name": "B",
                "type": "fixed_duration",
                "duration": 60,
                "dependencies": [],
                "resourceNeeded": "microscope",
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
            {"name": "A", "type": "fixed_duration", "duration": 5, "dependencies": [], "resourceNeeded": "x"},
        ],
    }
    r = client.post("/api/experiments", headers=auth_headers, json=payload)
    assert r.status_code == 201
    exp_id = r.get_json()["id"]

    r = client.get(f"/api/experiments/{exp_id}/conflicts", headers=second_user_headers)
    assert r.status_code == 404


def test_update_experiment_response_includes_conflicts(client, auth_headers):
    """PUT /api/experiments/<id> attaches the conflict list to the response so
    the Designer can surface it without an extra fetch (U6 contract).
    Notification emission for these is U7's responsibility -- this just
    validates the payload shape."""
    create_payload = {
        "name": "DesignerConflict",
        "description": "",
        "steps": [
            {"name": "A", "type": "fixed_duration", "duration": 60, "dependencies": [], "resourceNeeded": "microscope"},
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
                "type": created["steps"][0]["type"],
                "duration": created["steps"][0]["duration"],
                "dependencies": [],
                "resourceNeeded": "microscope",
            },
            {
                "name": "B",
                "type": "fixed_duration",
                "duration": 60,
                "dependencies": [],
                "resourceNeeded": "microscope",
            },
        ],
    }
    r = client.put(f"/api/experiments/{exp_id}", headers=auth_headers, json=update_payload)
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert "conflicts" in body
    assert len(body["conflicts"]) == 1
    assert body["conflicts"][0]["resource"] == "microscope"
