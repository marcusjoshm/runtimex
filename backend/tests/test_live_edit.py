"""U5 tests: reactive live-edit operations.

Two new endpoints under test:

  * ``POST /api/steps/<id>/extend``   -- extend / shrink the active step's
    duration. Re-runs conflict detection, persists, emits
    ``experiment_update``. Shrink-clamps when delta would push duration
    below current ``elapsed_seconds``.
  * ``POST /api/conditions/<id>/push`` -- shift PENDING/READY steps in a
    Condition by ``delta_seconds``. RUNNING/COMPLETED/SKIPPED/PAUSED stay
    put. Zero-delta is a documented no-op (no DB write, no socket emit).

Auth + permission policy mirrors existing step-state routes (U3):

  * View-share but no edit -> 403 ("edit permission required").
  * Unrelated user (cannot view the parent experiment) -> 404 (existence
    privacy: matches ``get_experiment`` semantics so attackers can't probe
    IDs to confirm membership).

Regression coverage for the U4 landmine the U4 subagent flagged: extending
a RUNNING step does NOT reset ``prewarnings_fired`` -- the user extended
deliberately and shouldn't see warnings they already received re-fire.
"""
from datetime import datetime, timedelta
from unittest.mock import patch

from models import StepStatus, StepORM
from tests.conftest import register_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _create_two_condition_experiment(client, headers):
    """Build an experiment with two Conditions, each with two scheduled steps.

    Layout:
      Condition A (condA, "A"):
        - stepA1 (Wash, microscope, 300s)
        - stepA2 (Image, microscope, 600s, depends on stepA1)
      Condition B (condB, "B"):
        - stepB1 (Wash, microscope, 300s)
        - stepB2 (Image, microscope, 600s, depends on stepB1)

    The microscope is shared across Conditions on purpose so a push that
    nudges Condition A into Condition B's window produces a cross-condition
    conflict (one of the test scenarios in the plan).

    All steps are TASKs so a force-RUNNING transition doesn't insist on a
    ``fixed_duration`` countdown loop in the client tick.
    """
    payload = {
        "name": "LiveEditExp",
        "description": "U5 live-edit fixture",
        "conditions": [
            {"id": "condA", "name": "A", "color": "slate", "order_index": 0},
            {"id": "condB", "name": "B", "color": "coral", "order_index": 1},
        ],
        "steps": [
            {
                "id": "stepA1",
                "name": "Wash A",
                "step_type": "task",
                "duration_seconds": 300,
                "condition_id": "condA",
                "resource_required": "microscope",
            },
            {
                "id": "stepA2",
                "name": "Image A",
                "step_type": "task",
                "duration_seconds": 600,
                "condition_id": "condA",
                "resource_required": "microscope",
                "dependencies": ["stepA1"],
            },
            {
                "id": "stepB1",
                "name": "Wash B",
                "step_type": "task",
                "duration_seconds": 300,
                "condition_id": "condB",
                "resource_required": "microscope",
            },
            {
                "id": "stepB2",
                "name": "Image B",
                "step_type": "task",
                "duration_seconds": 600,
                "condition_id": "condB",
                "resource_required": "microscope",
                "dependencies": ["stepB1"],
            },
        ],
    }
    r = client.post("/api/experiments", headers=headers, json=payload)
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def _share(client, owner_headers, experiment_id, target_username, permission):
    r = client.post(
        f"/api/experiments/{experiment_id}/share",
        headers=owner_headers,
        json={"username": target_username, "permission": permission},
    )
    assert r.status_code == 200, r.get_json()


def _set_step_state(step_id, *, status, elapsed_seconds=0.0):
    """Force a step into a given state for deterministic testing.

    The scheduler's normal start/pause/complete path drives the dataclass
    forward, but we want fine-grained control for the shrink-clamp scenario
    (where elapsed > new_duration matters).
    """
    import main as main_module

    with main_module.app.app_context():
        step = main_module.scheduler.get_step(step_id)
        step.status = status
        step.elapsed_time = timedelta(seconds=elapsed_seconds)
        if status == StepStatus.RUNNING:
            step.actual_start_time = datetime.now()
            step.first_start_time = step.actual_start_time
        main_module.scheduler._persist_step_state(step)


def _set_step_scheduled(step_id, start, end):
    """Override a step's scheduled_start/end. Helper for cross-condition
    overlap tests where we need deterministic schedule positions.
    """
    import main as main_module

    with main_module.app.app_context():
        step = main_module.scheduler.get_step(step_id)
        step.scheduled_start_time = start
        step.scheduled_end_time = end
        main_module.scheduler._persist_step_state(step)


def _read_step_orm(step_id):
    """Pull the persisted ORM row -- proves the cache + DB are coherent."""
    import main as main_module
    from db import db as _db

    with main_module.app.app_context():
        return _db.session.get(StepORM, step_id).__dict__.copy() if _db.session.get(StepORM, step_id) else None


def _step_from_response(payload, step_id):
    """Find a step in an ``experiment_to_dict``-shaped payload."""
    return next(s for s in payload["steps"] if s["id"] == step_id)


# ---------------------------------------------------------------------------
# 1. Happy path: extend (Covers AE4.)
# ---------------------------------------------------------------------------
def test_extend_step_happy_path(client, auth_headers):
    """`Covers AE4.` POST /api/steps/<id>/extend with delta_seconds=300.

    The step's ``duration_seconds`` becomes original+300; the response
    includes a ``conflicts`` field (matching update_experiment's shape) and
    the persisted state reflects the new duration.
    """
    exp = _create_two_condition_experiment(client, auth_headers)
    original_duration = next(
        s["duration_seconds"] for s in exp["steps"] if s["id"] == "stepA2"
    )

    r = client.post(
        "/api/steps/stepA2/extend",
        headers=auth_headers,
        json={"delta_seconds": 300},
    )
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert "conflicts" in body, "extend response must carry the post-mutation conflict list"

    step = _step_from_response(body, "stepA2")
    assert step["duration_seconds"] == original_duration + 300


# ---------------------------------------------------------------------------
# 2. Happy path: push condition shifts PENDING/READY only.
# ---------------------------------------------------------------------------
def test_push_condition_shifts_pending_and_ready_only(client, auth_headers):
    """POST /api/conditions/<id>/push with delta_seconds=600 must:

      * Shift all PENDING / READY steps in the target Condition by 600s
        (both ``scheduled_start_time`` AND ``scheduled_end_time``).
      * Leave RUNNING / COMPLETED / SKIPPED / PAUSED / ERROR steps alone.

    We force one step in Condition A to RUNNING so we can assert that path
    explicitly: it must NOT move even though it's in the pushed Condition.
    """
    _create_two_condition_experiment(client, auth_headers)

    # Capture pre-push schedule for stepA2 (PENDING) and stepA1 (we'll force RUNNING).
    import main as main_module
    with main_module.app.app_context():
        stepA1 = main_module.scheduler.get_step("stepA1")
        stepA2 = main_module.scheduler.get_step("stepA2")
        # stepA1 starts RUNNING -> should NOT be shifted by the push.
        a1_pre_start = stepA1.scheduled_start_time
        a1_pre_end = stepA1.scheduled_end_time
        # stepA2 stays PENDING -> SHOULD be shifted by 600s.
        a2_pre_start = stepA2.scheduled_start_time
        a2_pre_end = stepA2.scheduled_end_time

    _set_step_state("stepA1", status=StepStatus.RUNNING)

    r = client.post(
        "/api/conditions/condA/push",
        headers=auth_headers,
        json={"delta_seconds": 600},
    )
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert "conflicts" in body

    a1 = _step_from_response(body, "stepA1")
    a2 = _step_from_response(body, "stepA2")

    # RUNNING step must NOT have moved.
    if a1_pre_start:
        assert a1["scheduled_start_time"] == a1_pre_start.isoformat()
    if a1_pre_end:
        assert a1["scheduled_end_time"] == a1_pre_end.isoformat()

    # PENDING step MUST have moved by exactly 600s.
    if a2_pre_start:
        new_start = datetime.fromisoformat(a2["scheduled_start_time"])
        assert (new_start - a2_pre_start) == timedelta(seconds=600)
    if a2_pre_end:
        new_end = datetime.fromisoformat(a2["scheduled_end_time"])
        assert (new_end - a2_pre_end) == timedelta(seconds=600)


# ---------------------------------------------------------------------------
# 3. Edge case: shrink-clamp when delta would push duration below elapsed.
# ---------------------------------------------------------------------------
def test_extend_step_shrink_clamps_to_elapsed_plus_one(client, auth_headers):
    """A step with elapsed_time=120s; POST extend with delta=-200 (which
    would naively make duration -50). The endpoint clamps duration to
    elapsed+1 (=121s) and includes a ``warning`` field in the response.
    """
    _create_two_condition_experiment(client, auth_headers)
    # stepA1 has duration 300s; force it RUNNING with elapsed=120s.
    _set_step_state("stepA1", status=StepStatus.RUNNING, elapsed_seconds=120)

    r = client.post(
        "/api/steps/stepA1/extend",
        headers=auth_headers,
        json={"delta_seconds": -200},  # 300 - 200 = 100 < 120 elapsed -> clamp
    )
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body.get("warning") == "duration clamped to current elapsed"

    step = _step_from_response(body, "stepA1")
    assert step["duration_seconds"] == 121.0


# ---------------------------------------------------------------------------
# 4. Edge case: delta_seconds=0 on push is a no-op.
# ---------------------------------------------------------------------------
def test_push_condition_zero_delta_is_noop(client, auth_headers):
    """``delta_seconds=0`` returns 200 with the current experiment payload
    but performs NO mutation (no schedule shift, no DB write, no socket
    emit). We verify by snapshotting the step's scheduled_start_time and
    asserting it doesn't budge.
    """
    _create_two_condition_experiment(client, auth_headers)

    import main as main_module
    with main_module.app.app_context():
        before = main_module.scheduler.get_step("stepA2").scheduled_start_time

    # Patch _emit_experiment_update so we can verify it's NOT called on a
    # zero-delta push (the documented no-op).
    with patch.object(main_module, "_emit_experiment_update") as mock_emit:
        r = client.post(
            "/api/conditions/condA/push",
            headers=auth_headers,
            json={"delta_seconds": 0},
        )
        assert r.status_code == 200, r.get_json()
        assert mock_emit.call_count == 0, "zero-delta push must not emit"

    with main_module.app.app_context():
        after = main_module.scheduler.get_step("stepA2").scheduled_start_time
    assert after == before


# ---------------------------------------------------------------------------
# 5. Edge case: cross-condition impact -- pushing A causes B-overlap conflict.
# ---------------------------------------------------------------------------
def test_push_condition_surfaces_cross_condition_conflict(client, auth_headers):
    """Push Condition A by +600s into Condition B's microscope window. The
    response's ``conflicts`` list must include the resulting pair labelled
    with both conditions (per the U2 conflict-payload contract).

    We explicitly position the steps so the overlap is unambiguous:
      * stepA2 (Image A, microscope, 600s) at base..base+600s (pre-push)
      * stepB2 (Image B, microscope, 600s) at base+600s..base+1200s (no overlap)
      Push condA by +600s -> stepA2 lands at base+600..base+1200, fully
      overlapping stepB2.
    """
    _create_two_condition_experiment(client, auth_headers)
    base = datetime(2026, 1, 1, 14, 0, 0)
    _set_step_scheduled("stepA1", base - timedelta(seconds=300), base)
    _set_step_scheduled("stepA2", base, base + timedelta(seconds=600))
    _set_step_scheduled("stepB1", base + timedelta(seconds=300), base + timedelta(seconds=600))
    _set_step_scheduled("stepB2", base + timedelta(seconds=600), base + timedelta(seconds=1200))

    # Pre-push: with this layout there's already ONE microscope conflict
    # (stepA2's [base, base+600) overlaps stepB1's [base+300, base+600))
    # but NO conflict between stepA2 and stepB2 (they meet at boundary).
    # After push by +600s, stepA2 lands at [base+600, base+1200) which
    # fully overlaps stepB2.

    r = client.post(
        "/api/conditions/condA/push",
        headers=auth_headers,
        json={"delta_seconds": 600},
    )
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    conflicts = body["conflicts"]

    pair_keys = {tuple(sorted([c["step_a"], c["step_b"]])) for c in conflicts}
    assert ("stepA2", "stepB2") in pair_keys, (
        f"expected a cross-condition microscope conflict between stepA2 and stepB2, "
        f"got {pair_keys}"
    )

    cross_conflict = next(
        c for c in conflicts
        if tuple(sorted([c["step_a"], c["step_b"]])) == ("stepA2", "stepB2")
    )
    assert {cross_conflict["condition_a_name"], cross_conflict["condition_b_name"]} == {"A", "B"}


# ---------------------------------------------------------------------------
# 6. Error: unauthorized user (view-only) gets 403 on both endpoints.
# ---------------------------------------------------------------------------
def test_extend_view_share_blocked_with_403(client, auth_headers, second_user_headers):
    """View-share grants GET but blocks step-state mutations -- including
    extend. Mirrors ``can_run_step``'s policy on existing step routes.
    """
    exp = _create_two_condition_experiment(client, auth_headers)
    _share(client, auth_headers, exp["id"], "bob", "view")

    r = client.post(
        "/api/steps/stepA1/extend",
        headers=second_user_headers,
        json={"delta_seconds": 60},
    )
    assert r.status_code == 403
    assert r.get_json()["error"] == "edit permission required"


def test_push_condition_view_share_blocked_with_403(client, auth_headers, second_user_headers):
    """Same policy on the push endpoint: view-share -> 403."""
    exp = _create_two_condition_experiment(client, auth_headers)
    _share(client, auth_headers, exp["id"], "bob", "view")

    r = client.post(
        "/api/conditions/condA/push",
        headers=second_user_headers,
        json={"delta_seconds": 60},
    )
    assert r.status_code == 403
    assert r.get_json()["error"] == "edit permission required"


# ---------------------------------------------------------------------------
# 7. Error: foreign experiment user (unrelated) gets 404 on both endpoints.
# ---------------------------------------------------------------------------
def test_extend_unrelated_user_gets_404(client, auth_headers, second_user_headers):
    """Existence privacy: an unrelated user must see 404 on extend, not
    403. Otherwise they could probe IDs to confirm a step exists."""
    _create_two_condition_experiment(client, auth_headers)

    r = client.post(
        "/api/steps/stepA1/extend",
        headers=second_user_headers,
        json={"delta_seconds": 60},
    )
    assert r.status_code == 404


def test_push_condition_unrelated_user_gets_404(client, auth_headers, second_user_headers):
    """Existence privacy on the push endpoint mirrors the extend path.
    Foreign condition_id resolves to "no such experiment" from this caller's
    point of view."""
    _create_two_condition_experiment(client, auth_headers)

    r = client.post(
        "/api/conditions/condA/push",
        headers=second_user_headers,
        json={"delta_seconds": 60},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 8. Integration: experiment_update emits after successful mutations.
# ---------------------------------------------------------------------------
def test_extend_emits_experiment_update(client, auth_headers):
    """A successful extend fires the ``experiment_update`` socket broadcast
    so a second open Runner tab sees the change without polling. Asserted
    via patching ``_emit_experiment_update`` -- same approach as the U4
    socket tests' notification dispatch.
    """
    _create_two_condition_experiment(client, auth_headers)

    import main as main_module
    with patch.object(main_module, "_emit_experiment_update") as mock_emit:
        r = client.post(
            "/api/steps/stepA1/extend",
            headers=auth_headers,
            json={"delta_seconds": 60},
        )
        assert r.status_code == 200
        assert mock_emit.call_count == 1
        # The emit's argument is the experiment dataclass -- assert it's the
        # right one so a regression that swaps experiments doesn't slip past.
        emitted = mock_emit.call_args[0][0]
        assert emitted.id == r.get_json()["id"]


def test_push_condition_emits_experiment_update(client, auth_headers):
    """Same broadcast contract on the push endpoint."""
    _create_two_condition_experiment(client, auth_headers)

    import main as main_module
    with patch.object(main_module, "_emit_experiment_update") as mock_emit:
        r = client.post(
            "/api/conditions/condA/push",
            headers=auth_headers,
            json={"delta_seconds": 60},
        )
        assert r.status_code == 200
        assert mock_emit.call_count == 1


# ---------------------------------------------------------------------------
# 9. Regression: extend does NOT reset prewarnings_fired on a RUNNING step.
# ---------------------------------------------------------------------------
def test_extend_does_not_reset_prewarnings_fired(client, auth_headers):
    """U4 landmine guard: if the user extends a RUNNING step that has
    already fired a pre-warning, the prewarnings_fired list MUST stay
    intact. Otherwise the user would see the warning re-fire after every
    extend, which is exactly the noise pre-warnings exist to prevent.

    Setup: stepA1 (RUNNING) has prewarnings_fired = [60]. After extend +120,
    the persisted prewarnings_fired must still be [60].
    """
    _create_two_condition_experiment(client, auth_headers)
    _set_step_state("stepA1", status=StepStatus.RUNNING)

    # Force-fire a pre-warning so the test starts from a non-empty state.
    import main as main_module
    from db import db as _db
    with main_module.app.app_context():
        step = main_module.scheduler.get_step("stepA1")
        step.prewarning_offsets_seconds = [60]
        step.prewarnings_fired = [60]
        main_module.scheduler._persist_step_state(step)

    r = client.post(
        "/api/steps/stepA1/extend",
        headers=auth_headers,
        json={"delta_seconds": 120},
    )
    assert r.status_code == 200, r.get_json()

    with main_module.app.app_context():
        orm = _db.session.get(StepORM, "stepA1")
        assert list(orm.prewarnings_fired or []) == [60], (
            "extending a step must NOT reset prewarnings_fired -- "
            "the user extended deliberately and shouldn't see the warning re-fire"
        )


# ---------------------------------------------------------------------------
# 10. Validation: missing / non-numeric delta_seconds -> 400.
# ---------------------------------------------------------------------------
def test_extend_missing_delta_returns_400(client, auth_headers):
    _create_two_condition_experiment(client, auth_headers)
    r = client.post("/api/steps/stepA1/extend", headers=auth_headers, json={})
    assert r.status_code == 400
    assert "delta_seconds" in r.get_json()["error"]


def test_push_non_numeric_delta_returns_400(client, auth_headers):
    _create_two_condition_experiment(client, auth_headers)
    r = client.post(
        "/api/conditions/condA/push",
        headers=auth_headers,
        json={"delta_seconds": "not-a-number"},
    )
    assert r.status_code == 400
