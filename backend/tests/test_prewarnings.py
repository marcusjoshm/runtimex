"""U4 tests: pre-warnings (data + handler + dedupe).

The plan's contract for pre-warnings is "client fires + server dedupes":
clients tick once per second, emit ``prewarning_hit`` whenever an offset
threshold is crossed; the server appends to ``prewarnings_fired`` exactly
once and fires a notification factory the FIRST time. Subsequent emits for
the same (step, offset) are silent no-ops.

These tests exercise the SocketIO handler directly via the test_client
mechanism Flask-SocketIO ships, asserting the persisted side-effects:

  * ``StepORM.prewarnings_fired`` gains the offset on a fresh fire.
  * ``NotificationORM`` gets a ``step_prewarning`` row for the experiment owner.
  * Duplicate emits do NOT add a second notification or a second list entry.
  * Multiple distinct offsets (e.g., ``[600, 60]``) each fire independently.
  * Offsets > duration fire (acceptable per the plan -- the threshold is
    crossed at T=0).
  * Undeclared offsets are rejected silently.
  * Cross-user view denial is silent (existence-privacy match).
  * The persisted notification surfaces via
    ``notification_service.get_user_notifications`` (the same path the GET
    /api/notifications route uses).
"""
from datetime import datetime, timedelta

from flask_socketio import SocketIOTestClient

from models import StepStatus, StepORM
from notifications import NotificationType
from tests.conftest import register_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _create_experiment_with_prewarning(
    client,
    headers,
    *,
    name="PreWarnExp",
    duration_seconds=1800,
    offsets=(600,),
):
    """Create a single-Condition, single-Step experiment with pre-warnings.

    The step is a ``fixed_duration`` so START semantics are simple. We assign
    a known step id and condition id so subsequent direct SQL / scheduler
    pokes are deterministic.
    """
    payload = {
        "name": name,
        "description": "U4 prewarning test",
        "conditions": [
            {"id": "condA", "name": "A", "color": "slate", "order_index": 0},
        ],
        "steps": [
            {
                "id": "stepA",
                "name": "Imaging",
                "step_type": "fixed_duration",
                "duration_seconds": duration_seconds,
                "condition_id": "condA",
                "prewarning_offsets_seconds": list(offsets),
            },
        ],
    }
    r = client.post("/api/experiments", headers=headers, json=payload)
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def _socket_client(app, token):
    """Build an authed SocketIOTestClient for the running app.

    flask-jwt-extended's default ``JWT_QUERY_STRING_NAME`` is ``jwt``, so the
    token must ride as ``?jwt=<token>`` for ``verify_jwt_in_request(
    locations=['query_string'])`` to find it. (The frontend socket.io client
    in client.ts uses ``?token=...``; that's a pre-existing wire-name
    mismatch tracked outside this unit -- we test against the server's
    actual contract here.)
    """
    import main as main_module

    return SocketIOTestClient(
        app,
        main_module.socketio,
        query_string=f"jwt={token}",
    )


def _token_from_headers(headers):
    return headers["Authorization"].removeprefix("Bearer ").strip()


def _owner_prewarning_notifications(owner_username, step_id=None):
    """Pull the ``step_prewarning`` notifications for ``owner_username``.

    Optional filter by ``step_id`` so a multi-step experiment doesn't bleed
    other steps' fires into the assertion.
    """
    import main as main_module

    with main_module.app.app_context():
        rows = main_module.notification_service.get_user_notifications(owner_username)
    rows = [n for n in rows if n.type == NotificationType.STEP_PREWARNING]
    if step_id is not None:
        rows = [n for n in rows if n.step_id == step_id]
    return rows


def _force_running(step_id):
    """Drive a step into RUNNING state with an actual_start_time of "now"."""
    import main as main_module

    with main_module.app.app_context():
        step = main_module.scheduler.get_step(step_id)
        step.status = StepStatus.RUNNING
        step.actual_start_time = datetime.now()
        step.first_start_time = step.actual_start_time
        main_module.scheduler._persist_step_state(step)


def _step_orm_state(step_id):
    """Read the persisted JSON columns for a step. Use INSIDE app_context."""
    import main as main_module
    from db import db as _db

    with main_module.app.app_context():
        row = _db.session.get(StepORM, step_id)
        return {
            "prewarning_offsets_seconds": list(row.prewarning_offsets_seconds or []),
            "prewarnings_fired": list(row.prewarnings_fired or []),
        }


# ---------------------------------------------------------------------------
# 1. Happy path: AE3. Fresh fire appends to prewarnings_fired + emits notification.
# ---------------------------------------------------------------------------
def test_ae3_prewarning_hit_appends_and_emits(app, client, auth_headers):
    """`Covers AE3.` 1800s step with offset [600]; emit prewarning_hit at
    "T=1200" semantically (offset=600 means "10 min remaining"). Server should
    append 600 to prewarnings_fired and persist exactly one notification."""
    exp = _create_experiment_with_prewarning(
        client, auth_headers, duration_seconds=1800, offsets=(600,)
    )
    _force_running("stepA")

    sock = _socket_client(app, _token_from_headers(auth_headers))
    assert sock.is_connected()
    sock.emit("prewarning_hit", {"step_id": "stepA", "offset_seconds": 600})

    state = _step_orm_state("stepA")
    assert state["prewarning_offsets_seconds"] == [600]
    assert state["prewarnings_fired"] == [600]

    notifs = _owner_prewarning_notifications("alice", step_id="stepA")
    assert len(notifs) == 1
    assert notifs[0].step_id == "stepA"
    # Title and body should both include the human-readable label for 600s.
    assert "10 minutes" in notifs[0].message
    assert notifs[0].metadata.get("offset_seconds") == 600

    sock.disconnect()


# ---------------------------------------------------------------------------
# 2. Edge case (dedupe): two events for offset 600 => one notification.
# ---------------------------------------------------------------------------
def test_duplicate_prewarning_hit_is_idempotent(app, client, auth_headers):
    """A second emit for the same (step, offset) is a silent no-op. Persisted
    state and notification count both stay at 1."""
    _create_experiment_with_prewarning(
        client, auth_headers, duration_seconds=1800, offsets=(600,)
    )
    _force_running("stepA")

    sock = _socket_client(app, _token_from_headers(auth_headers))
    sock.emit("prewarning_hit", {"step_id": "stepA", "offset_seconds": 600})
    sock.emit("prewarning_hit", {"step_id": "stepA", "offset_seconds": 600})

    state = _step_orm_state("stepA")
    assert state["prewarnings_fired"] == [600], (
        "dedupe contract: prewarnings_fired must contain offset 600 exactly once"
    )

    notifs = _owner_prewarning_notifications("alice", step_id="stepA")
    assert len(notifs) == 1, (
        f"expected 1 prewarning notification (dedupe), got {len(notifs)}"
    )

    sock.disconnect()


# ---------------------------------------------------------------------------
# 3. Edge case (multiple offsets): two separate offsets fire two notifications.
# ---------------------------------------------------------------------------
def test_multiple_distinct_offsets_each_fire_once(app, client, auth_headers):
    """A step with offsets [600, 60] emits two distinct notifications, one
    per offset, when both events arrive. The dedupe is per-offset, not
    per-step."""
    _create_experiment_with_prewarning(
        client, auth_headers, duration_seconds=1800, offsets=(600, 60)
    )
    _force_running("stepA")

    sock = _socket_client(app, _token_from_headers(auth_headers))
    sock.emit("prewarning_hit", {"step_id": "stepA", "offset_seconds": 600})
    sock.emit("prewarning_hit", {"step_id": "stepA", "offset_seconds": 60})

    state = _step_orm_state("stepA")
    assert sorted(state["prewarnings_fired"]) == [60, 600]

    notifs = _owner_prewarning_notifications("alice", step_id="stepA")
    assert len(notifs) == 2
    fired_offsets = sorted(n.metadata.get("offset_seconds") for n in notifs)
    assert fired_offsets == [60, 600]

    sock.disconnect()


# ---------------------------------------------------------------------------
# 4. Edge case (offset > duration): fires once on a fresh emit.
# ---------------------------------------------------------------------------
def test_offset_larger_than_duration_fires_once(app, client, auth_headers):
    """Per the plan: offset 3600 on a 600s step is acceptable -- the threshold
    is crossed at T=0 (``expected_end - now = 600 - 0 = 600 <= 3600``) and a
    single fire happens. This test asserts the single-fire shape; the fact
    that the threshold is crossed early is a Designer-time UX consideration
    that the backend doesn't reject."""
    _create_experiment_with_prewarning(
        client, auth_headers, duration_seconds=600, offsets=(3600,)
    )
    _force_running("stepA")

    sock = _socket_client(app, _token_from_headers(auth_headers))
    sock.emit("prewarning_hit", {"step_id": "stepA", "offset_seconds": 3600})

    state = _step_orm_state("stepA")
    assert state["prewarnings_fired"] == [3600]
    notifs = _owner_prewarning_notifications("alice", step_id="stepA")
    assert len(notifs) == 1

    sock.disconnect()


# ---------------------------------------------------------------------------
# 5. Error path: undeclared offset_seconds is silently rejected.
# ---------------------------------------------------------------------------
def test_undeclared_offset_is_silently_rejected(app, client, auth_headers):
    """A client that emits prewarning_hit for an offset NOT in the step's
    declared list must NOT mutate persisted state and must NOT fire a
    notification. The server doesn't trust offsets the client invents --
    that would be a notification-spam vector."""
    _create_experiment_with_prewarning(
        client, auth_headers, duration_seconds=1800, offsets=(600,)
    )
    _force_running("stepA")

    sock = _socket_client(app, _token_from_headers(auth_headers))
    # Emit for an offset NOT in the step's declared list.
    sock.emit("prewarning_hit", {"step_id": "stepA", "offset_seconds": 999})

    state = _step_orm_state("stepA")
    assert state["prewarnings_fired"] == []
    notifs = _owner_prewarning_notifications("alice", step_id="stepA")
    assert len(notifs) == 0

    sock.disconnect()


# ---------------------------------------------------------------------------
# 6. Error path: caller without view permission gets a silent no-op.
# ---------------------------------------------------------------------------
def test_unviewable_step_is_silent_no_op(app, client, auth_headers):
    """A second user (``bob``) who can't view alice's experiment cannot
    fire a prewarning_hit for it. No DB write, no notification, no error
    feedback (existence-privacy: matches the rest of the API).
    """
    _create_experiment_with_prewarning(
        client, auth_headers, duration_seconds=1800, offsets=(600,)
    )
    _force_running("stepA")

    bob_headers = register_user(client, "bob", "bob@example.com", "secret456")

    sock = _socket_client(app, _token_from_headers(bob_headers))
    sock.emit("prewarning_hit", {"step_id": "stepA", "offset_seconds": 600})

    state = _step_orm_state("stepA")
    assert state["prewarnings_fired"] == []
    # No notification for either user.
    alice_notifs = _owner_prewarning_notifications("alice", step_id="stepA")
    bob_notifs = _owner_prewarning_notifications("bob", step_id="stepA")
    assert alice_notifs == []
    assert bob_notifs == []

    sock.disconnect()


# ---------------------------------------------------------------------------
# 7. Integration: persisted notification visible via the same path GET reads.
# ---------------------------------------------------------------------------
def test_prewarning_notification_visible_to_owner(app, client, auth_headers):
    """The ``step_prewarning`` notification persisted by the handler is
    queryable by ``notification_service.get_user_notifications`` -- which is
    exactly the path the GET /api/notifications HTTP route reads. This is
    the durable contract: an offline owner will see the warning on next
    page load even if their socket missed the live emit."""
    _create_experiment_with_prewarning(
        client, auth_headers, duration_seconds=1800, offsets=(600,)
    )
    _force_running("stepA")

    sock = _socket_client(app, _token_from_headers(auth_headers))
    sock.emit("prewarning_hit", {"step_id": "stepA", "offset_seconds": 600})
    sock.disconnect()

    # Hitting the HTTP layer the same way the frontend NotificationCenter does.
    r = client.get("/api/notifications", headers=auth_headers)
    assert r.status_code == 200
    body = r.get_json()
    prewarnings = [n for n in body if n["type"] == "step_prewarning"]
    assert len(prewarnings) == 1
    assert prewarnings[0]["step_id"] == "stepA"
    assert prewarnings[0]["title"].startswith("Pre-warning:")
