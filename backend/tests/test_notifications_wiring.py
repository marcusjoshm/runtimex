"""Notification wiring tests for U7.

The notification SERVICE was already fully built (storage + socket emit) by
U2; what U7 wires is the call sites in the real route handlers and the
fan-out to dependents on a step transition.

These tests assert end-to-end behaviour through the HTTP layer:

* Completing a step that unblocks a dependent emits exactly one
  ``step_ready`` notification per dependent (to the experiment's owner).
* Completing the LAST step in a chain emits exactly one ``step_completed``
  and zero ``step_ready``.
* Saving an experiment with two overlapping resource users emits one
  ``resource_conflict`` notification.
* A user with no live socket (logged out / not connected) still gets the
  persisted DB row -- the room emit is best-effort, the row is the
  durable thing that survives "I logged in later".
* The owner of the experiment is the recipient (``target_user``), not the
  requesting user (regression test for shared-edit clients calling
  ``complete`` on a non-owner's experiment).

We poke at notifications via ``notification_service.get_user_notifications``
which queries the same ``NotificationORM`` table that the GET route
serializes -- so a "row written" assertion here is the same row a logged-in
user would see on next page load.
"""
from datetime import datetime, timedelta

from models import StepStatus
from notifications import NotificationType
from tests.conftest import register_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _create_experiment_with_chain(client, headers, name="WiringExp"):
    """Build a 2-step experiment where S2 depends on S1.

    Returns the JSON payload from the create call. Both steps have type
    ``task`` so they can be skipped/started/completed without the
    FIXED_DURATION timer machinery getting in the way.
    """
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
    body = r.get_json()

    # Wire S2.dependencies = [S1.id] via the PUT route. We do this
    # post-create so we can reference the assigned UUIDs.
    s1_id = body["steps"][0]["id"]
    s2_id = body["steps"][1]["id"]
    update = {
        "name": body["name"],
        "description": body["description"],
        "steps": [
            {
                "id": s1_id,
                "name": "S1",
                "type": "task",
                "duration": 5,
                "dependencies": [],
            },
            {
                "id": s2_id,
                "name": "S2",
                "type": "task",
                "duration": 7,
                "dependencies": [s1_id],
            },
        ],
    }
    r = client.put(f"/api/experiments/{body['id']}", headers=headers, json=update)
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def _force_step(step_id, status: StepStatus, *, set_actual_start=False):
    """Bypass the scheduler state machine so we can drive transitions deterministically.

    The notification call sites care about transitions (READY -> COMPLETED ->
    dependent flips to READY); they don't care HOW we got there.
    """
    import main as main_module

    with main_module.app.app_context():
        step = main_module.scheduler.get_step(step_id)
        step.status = status
        if set_actual_start and step.actual_start_time is None:
            step.actual_start_time = datetime.now() - timedelta(seconds=1)
            step.first_start_time = step.actual_start_time


def _owner_notifications(owner_username, ntype: NotificationType = None):
    """Pull persisted notifications for a user, optionally filtered by type."""
    import main as main_module

    with main_module.app.app_context():
        rows = main_module.notification_service.get_user_notifications(owner_username)
    if ntype is not None:
        return [n for n in rows if n.type == ntype]
    return rows


# ---------------------------------------------------------------------------
# 1. Completing a step unblocks dependents -> one step_ready per dependent.
# ---------------------------------------------------------------------------
def test_complete_emits_step_ready_for_each_unblocked_dependent(client, auth_headers):
    """Owner ``alice`` owns an experiment with S2 depending on S1.

    On ``POST /api/steps/<S1>/complete`` we expect:
      * exactly one ``step_completed`` notification (for S1)
      * exactly one ``step_ready`` notification (for S2 transitioning to READY)
    """
    exp = _create_experiment_with_chain(client, auth_headers, "ChainComplete")
    s1_id = exp["steps"][0]["id"]
    s2_id = exp["steps"][1]["id"]

    # Drive S1 into RUNNING so complete() accepts the transition. Force S2
    # back to PENDING so the post-complete update_ready_status loop is the
    # thing that flips it to READY (which is what U7's notification fan-out
    # keys off). Without this, S2 is READY at create-time since dependency
    # wiring goes through PUT after both steps already entered the schedule.
    _force_step(s1_id, StepStatus.RUNNING, set_actual_start=True)
    _force_step(s2_id, StepStatus.PENDING)

    r = client.post(f"/api/steps/{s1_id}/complete", headers=auth_headers)
    assert r.status_code == 200, r.get_json()

    completed = _owner_notifications("alice", NotificationType.STEP_COMPLETED)
    ready = _owner_notifications("alice", NotificationType.STEP_READY)

    assert len(completed) == 1
    assert completed[0].step_id == s1_id

    assert len(ready) == 1
    assert ready[0].step_id == s2_id


# ---------------------------------------------------------------------------
# 2. Completing the LAST step emits step_completed and zero step_ready.
# ---------------------------------------------------------------------------
def test_complete_last_step_emits_no_step_ready(client, auth_headers):
    """Single-step experiment: completion has no dependents to unblock."""
    payload = {
        "name": "Solo",
        "description": "",
        "steps": [
            {"name": "Only", "duration": 3, "type": "task", "dependencies": []},
        ],
    }
    r = client.post("/api/experiments", headers=auth_headers, json=payload)
    assert r.status_code == 201, r.get_json()
    step_id = r.get_json()["steps"][0]["id"]

    _force_step(step_id, StepStatus.RUNNING, set_actual_start=True)

    r = client.post(f"/api/steps/{step_id}/complete", headers=auth_headers)
    assert r.status_code == 200, r.get_json()

    completed = _owner_notifications("alice", NotificationType.STEP_COMPLETED)
    ready = _owner_notifications("alice", NotificationType.STEP_READY)

    assert len(completed) == 1
    assert len(ready) == 0


# ---------------------------------------------------------------------------
# 3. Saving an experiment with overlapping resource users emits one conflict.
# ---------------------------------------------------------------------------
def test_save_with_overlapping_resources_emits_one_conflict_notification(client, auth_headers):
    """PUT /api/experiments/<id> with two overlapping resource users -> one
    ``resource_conflict`` notification per conflict pair (here: 1).

    The conflict list is also attached to the response payload by U6;
    U7 layers the notification fan-out on top.
    """
    create_payload = {
        "name": "ConflictWiring",
        "description": "",
        "steps": [
            {
                "name": "A",
                "type": "fixed_duration",
                "duration": 60,
                "dependencies": [],
                "resourceNeeded": "microscope",
            },
        ],
    }
    r = client.post("/api/experiments", headers=auth_headers, json=create_payload)
    assert r.status_code == 201
    exp = r.get_json()
    exp_id = exp["id"]
    a_id = exp["steps"][0]["id"]

    # Snapshot any existing notifications so the assertion isolates the
    # conflict emit (the create call doesn't fan out conflicts -- only the
    # update path does, per the U7 contract).
    pre_conflicts = _owner_notifications("alice", NotificationType.RESOURCE_CONFLICT)

    update_payload = {
        "name": "ConflictWiring",
        "description": "",
        "steps": [
            {
                "id": a_id,
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
    r = client.put(f"/api/experiments/{exp_id}", headers=auth_headers, json=update_payload)
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert len(body["conflicts"]) == 1

    post_conflicts = _owner_notifications("alice", NotificationType.RESOURCE_CONFLICT)
    new_conflicts = post_conflicts[: len(post_conflicts) - len(pre_conflicts)]

    assert len(new_conflicts) == 1
    assert new_conflicts[0].metadata.get("resource") == "microscope"


# ---------------------------------------------------------------------------
# 4. Logged-out user still gets the DB row (room emit is best-effort).
# ---------------------------------------------------------------------------
def test_logged_out_user_receives_db_row_on_next_login(client, auth_headers):
    """Even though we never connected a socket in this test, the
    ``NotificationORM`` row is still written. That's the durable contract:
    "I missed the live emit, but I see it on next page load."

    This test is largely a regression guard: the current implementation
    always writes to DB before emitting, but a future refactor that flips
    the order (or skips the write when no rooms are listening) would
    silently regress the "logged-in later" UX.
    """
    exp = _create_experiment_with_chain(client, auth_headers, "OfflineUser")
    s1_id = exp["steps"][0]["id"]
    _force_step(s1_id, StepStatus.RUNNING, set_actual_start=True)

    # No socket connection in this test client -- we hit only HTTP. The
    # complete route still triggers ``add_notification``, which writes to DB
    # whether or not anyone is in the user's socket room.
    r = client.post(f"/api/steps/{s1_id}/complete", headers=auth_headers)
    assert r.status_code == 200

    # The row is durable and can be read by a later GET.
    rows = _owner_notifications("alice")
    assert any(n.type == NotificationType.STEP_COMPLETED for n in rows)


# ---------------------------------------------------------------------------
# 5. Recipient is the experiment owner, not the requesting user.
# ---------------------------------------------------------------------------
def test_notification_target_user_is_owner_not_requester(client, auth_headers):
    """A shared-edit user (``bob``) completes a step on Alice's experiment.

    Notifications must land on ``alice`` (the owner), NOT on ``bob`` (the
    actor). This is the regression test for "I shared my run with a
    teammate; their actions should appear in MY inbox".
    """
    bob_headers = register_user(client, "bob", "bob@example.com", "secret456")

    exp = _create_experiment_with_chain(client, auth_headers, "SharedEdit")
    exp_id = exp["id"]
    s1_id = exp["steps"][0]["id"]

    # Alice grants Bob edit permission.
    r = client.post(
        f"/api/experiments/{exp_id}/share",
        headers=auth_headers,
        json={"username": "bob", "permission": "edit"},
    )
    assert r.status_code == 200, r.get_json()

    _force_step(s1_id, StepStatus.RUNNING, set_actual_start=True)

    # Bob completes the step.
    r = client.post(f"/api/steps/{s1_id}/complete", headers=bob_headers)
    assert r.status_code == 200, r.get_json()

    alice_rows = _owner_notifications("alice", NotificationType.STEP_COMPLETED)
    bob_rows = _owner_notifications("bob", NotificationType.STEP_COMPLETED)

    assert len(alice_rows) == 1
    assert len(bob_rows) == 0
