"""Step-state tests for U5.

Covers:

* ``POST /api/steps/<id>/skip`` route (happy path, view-share blocked, unrelated
  user existence-privacy).
* ``Step.get_expected_end_time`` for RUNNING vs PAUSED, accounting for the
  accumulated ``elapsed_time``.
* ``Step.first_start_time`` set on first start only, preserved on resume.

The skip route is the symmetric counterpart of the existing complete route;
its tests mirror ``test_permissions.py``'s shape on purpose.
"""
from datetime import datetime, timedelta

from models import Step, StepStatus, StepType
from tests.conftest import register_user


# ---------------------------------------------------------------------------
# Helpers (kept local so we don't tangle test_permissions.py)
# ---------------------------------------------------------------------------
def _create_experiment(client, headers, name="StepsExp"):
    payload = {
        "name": name,
        "description": "test",
        "steps": [
            {"name": "S1", "duration": 5, "type": "task", "dependencies": []},
            {"name": "S2", "duration": 7, "type": "task", "dependencies": []},
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


def _force_step_ready(step_id):
    """Bypass the scheduler READY-check so transitions are deterministic."""
    import main as main_module

    with main_module.app.app_context():
        step = main_module.scheduler.get_step(step_id)
        step.status = StepStatus.READY


# ---------------------------------------------------------------------------
# 1-3. POST /api/steps/<id>/skip route
# ---------------------------------------------------------------------------
def test_skip_route_transitions_step_to_skipped(client, auth_headers):
    """Owner skips a READY step -> response shows status=SKIPPED."""
    exp = _create_experiment(client, auth_headers, "SkipExp")
    step_id = exp["steps"][0]["id"]
    _force_step_ready(step_id)

    r = client.post(f"/api/steps/{step_id}/skip", headers=auth_headers)
    assert r.status_code == 200, r.get_json()

    payload = r.get_json()
    skipped = next(s for s in payload["steps"] if s["id"] == step_id)
    assert skipped["status"] == StepStatus.SKIPPED.value


def test_skip_route_requires_edit_permission(client, auth_headers, second_user_headers):
    """A user with view-only share is blocked from skipping (403)."""
    exp = _create_experiment(client, auth_headers, "SkipViewShareExp")
    exp_id = exp["id"]
    step_id = exp["steps"][0]["id"]

    _share(client, auth_headers, exp_id, "bob", "view")
    _force_step_ready(step_id)

    r = client.post(f"/api/steps/{step_id}/skip", headers=second_user_headers)
    assert r.status_code == 403
    assert r.get_json()["error"] == "edit permission required"


def test_skip_route_unrelated_user_gets_404(client, auth_headers, second_user_headers):
    """Unrelated user gets 404 (existence privacy), not 403."""
    exp = _create_experiment(client, auth_headers, "SkipPrivateExp")
    step_id = exp["steps"][0]["id"]
    _force_step_ready(step_id)

    r = client.post(f"/api/steps/{step_id}/skip", headers=second_user_headers)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 4. Expected-end-time math: RUNNING accounts for elapsed_time
# ---------------------------------------------------------------------------
def test_get_expected_end_time_running_accounts_for_elapsed():
    """A RUNNING step that's been running 10s on a 60s budget should return
    actual_start_time + 50s (NOT actual_start_time + 60s).

    The pre-U5 implementation returned ``actual_start_time + duration``
    unconditionally, ignoring elapsed_time -- which is wrong the moment a
    step is paused-resumed (elapsed grows but the math kept saying the step
    had its full original duration left).
    """
    step = Step(name="run", duration=timedelta(seconds=60), step_type=StepType.TASK)
    # Step.start() refuses to transition out of PENDING; flip to READY first.
    step.status = StepStatus.READY
    start = datetime(2026, 1, 1, 12, 0, 0)
    step.start(start_time=start)

    # Simulate 10s of elapsed time accumulated through a previous pause/resume cycle.
    step.elapsed_time = timedelta(seconds=10)

    expected_end = step.get_expected_end_time()
    # actual_start_time + (duration - elapsed_time) == start + 50s.
    assert expected_end == start + timedelta(seconds=50)
    # Sanity: NOT start + 60s (would imply we ignored elapsed_time).
    assert expected_end != start + timedelta(seconds=60)


def test_get_expected_end_time_paused_uses_remaining():
    """A PAUSED step with 10s elapsed on a 60s budget should return
    now + 50s (within a 1-second tolerance for test wall-clock skew)."""
    step = Step(name="paused", duration=timedelta(seconds=60), step_type=StepType.TASK)
    step.status = StepStatus.READY
    # Start 30s in the past so when we pause "now", elapsed_time gets ~10s
    # added. Easier to set elapsed_time directly so the test is deterministic.
    step.start(start_time=datetime.now() - timedelta(seconds=10))
    step.pause()
    # ``pause()`` accumulated ~10s; lock it in for a deterministic comparison.
    step.elapsed_time = timedelta(seconds=10)

    before = datetime.now()
    expected_end = step.get_expected_end_time()
    after = datetime.now()

    # expected_end should be ~now + 50s. Allow a 2s window to cover any
    # interleaved wall-clock motion between ``before`` and the call.
    assert (before + timedelta(seconds=49)) <= expected_end <= (after + timedelta(seconds=51))


# ---------------------------------------------------------------------------
# 5. first_start_time semantics
# ---------------------------------------------------------------------------
def test_step_first_start_time_set_on_first_start_only():
    """First start sets first_start_time. Resume from PAUSED leaves it alone."""
    step = Step(name="resumable", duration=timedelta(seconds=60), step_type=StepType.TASK)
    step.status = StepStatus.READY

    first_start = datetime(2026, 1, 1, 12, 0, 0)
    step.start(start_time=first_start)
    assert step.first_start_time == first_start
    assert step.actual_start_time == first_start

    # Pause, then resume at a later time.
    step.pause()
    later = datetime(2026, 1, 1, 12, 5, 0)
    step.start(start_time=later)
    # actual_start_time has moved to the resume instant...
    assert step.actual_start_time == later
    # ...but first_start_time is preserved.
    assert step.first_start_time == first_start
