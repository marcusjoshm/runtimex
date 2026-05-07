"""U3 tests: cascading time across adjacent steps.

Covers the plan's six test scenarios:

* Happy path (Covers AE2): wash -> re-incubate; clicking START on Re-incubate
  seeds its elapsed_seconds from Wash's final elapsed.
* Edge case (chain): A -> B -> C all inheriting "previous"; C's seed is B's
  final elapsed (which already contains A's contribution); no double-count.
* Edge case (incomplete previous): START with an incomplete predecessor logs a
  warning and proceeds with elapsed_seconds = 0.
* Edge case (first in condition): "previous" with no preceding sibling -- silent
  no-op, elapsed_seconds = 0.
* Edge case (cross-condition reference): direct step-id reference into another
  Condition -- ignored with a warning.
* Integration: a RUNNING step that already inherited survives a restart with
  its seeded elapsed_seconds intact.
"""
from datetime import datetime, timedelta

import logging

import pytest

from models import StepStatus


def _create_chain(client, auth_headers, name="Cascade"):
    """Build a single-Condition experiment with two steps: Wash -> Re-incubate.

    Wash duration = 4 min (240s). Re-incubate duration = 30 min (1800s).
    Re-incubate's ``inherits_elapsed_from`` is set to ``"previous"`` so START on
    it should seed elapsed_seconds = 240.
    """
    payload = {
        "name": name,
        "description": "AE2 cascade",
        "conditions": [
            {"id": "condA", "name": "Condition A", "color": "coral", "order_index": 0},
        ],
        "steps": [
            {
                "id": "wash",
                "name": "Wash",
                "step_type": "fixed_duration",
                "duration_seconds": 240,
                "condition_id": "condA",
            },
            {
                "id": "reincubate",
                "name": "Re-incubate",
                "step_type": "fixed_duration",
                "duration_seconds": 1800,
                "condition_id": "condA",
                "inherits_elapsed_from": "previous",
            },
        ],
    }
    r = client.post("/api/experiments", headers=auth_headers, json=payload)
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def _force_complete(step_id, elapsed_seconds, end_time=None):
    """Drive a step to COMPLETED with a known elapsed_time, persisting via the
    scheduler so the ORM mirror picks it up too."""
    import main as main_module

    with main_module.app.app_context():
        step = main_module.scheduler.get_step(step_id)
        step.elapsed_time = timedelta(seconds=elapsed_seconds)
        step.actual_end_time = end_time or datetime.now()
        step.status = StepStatus.COMPLETED
        main_module.scheduler._persist_step_state(step)


def _force_ready(step_id):
    import main as main_module
    with main_module.app.app_context():
        step = main_module.scheduler.get_step(step_id)
        step.status = StepStatus.READY


# ---------------------------------------------------------------------------
# 1. Happy path: AE2 wash -> re-incubate.
# ---------------------------------------------------------------------------
def test_ae2_reincubate_inherits_elapsed_from_wash(client, auth_headers):
    """`Covers AE2.` Wash takes 4 min; START on Re-incubate seeds elapsed=240s."""
    exp = _create_chain(client, auth_headers, name="AE2 Cascade")

    # Drive Wash to COMPLETED with elapsed=240.
    _force_complete("wash", elapsed_seconds=240)

    # Start the Re-incubate step. This should pre-seed its elapsed_time.
    _force_ready("reincubate")
    r = client.post("/api/steps/reincubate/start", headers=auth_headers)
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    re = next(s for s in body["steps"] if s["id"] == "reincubate")
    assert re["status"] == StepStatus.RUNNING.value
    # Server emits ``elapsed_seconds`` only when non-zero. The seed should be
    # exactly 240s -- the Wash step's final elapsed.
    assert re["elapsed_seconds"] == pytest.approx(240.0, abs=0.5)

    # Countdown formula: duration - elapsed = 1800 - 240 = 1560s = 26 minutes.
    remaining = re["duration_seconds"] - re["elapsed_seconds"]
    assert remaining == pytest.approx(1560.0, abs=0.5)
    assert remaining / 60 == pytest.approx(26.0, abs=0.05)


# ---------------------------------------------------------------------------
# 2. Edge case: A -> B -> C chain. C's seed = B's final elapsed (no double-count).
# ---------------------------------------------------------------------------
def test_chain_does_not_double_count(client, auth_headers):
    """When A -> B (B inherits) -> C (C inherits), C seeds from B's FINAL
    elapsed, which already includes A's contribution. C must NOT additionally
    add A's elapsed on top -- the cascade composes naturally, not recursively.
    """
    payload = {
        "name": "ChainCascade",
        "conditions": [
            {"id": "cA", "name": "A", "color": "coral", "order_index": 0},
        ],
        "steps": [
            {"id": "stepA", "name": "A", "step_type": "fixed_duration", "duration_seconds": 100, "condition_id": "cA"},
            {
                "id": "stepB",
                "name": "B",
                "step_type": "fixed_duration",
                "duration_seconds": 600,
                "condition_id": "cA",
                "inherits_elapsed_from": "previous",
            },
            {
                "id": "stepC",
                "name": "C",
                "step_type": "fixed_duration",
                "duration_seconds": 1200,
                "condition_id": "cA",
                "inherits_elapsed_from": "previous",
            },
        ],
    }
    r = client.post("/api/experiments", headers=auth_headers, json=payload)
    assert r.status_code == 201, r.get_json()

    # A completes with elapsed=100.
    _force_complete("stepA", elapsed_seconds=100)
    # B completes with elapsed=300 (its final elapsed already INCLUDES the
    # inherited 100 + 200s of its own runtime).
    _force_complete("stepB", elapsed_seconds=300)
    # C starts -- should seed from B's final elapsed (300), NOT from B's 300 +
    # A's 100 = 400.
    _force_ready("stepC")
    r = client.post("/api/steps/stepC/start", headers=auth_headers)
    assert r.status_code == 200, r.get_json()
    c = next(s for s in r.get_json()["steps"] if s["id"] == "stepC")
    assert c["elapsed_seconds"] == pytest.approx(300.0, abs=0.5), (
        f"expected 300s seed (B's final elapsed), got {c.get('elapsed_seconds')} "
        "-- if this is 400 the cascade is double-counting"
    )


# ---------------------------------------------------------------------------
# 3. Edge case: previous step hasn't completed yet -> warn + elapsed=0.
# ---------------------------------------------------------------------------
def test_incomplete_previous_skips_inherit(client, auth_headers, caplog):
    """If the predecessor has NOT completed (no actual_end_time), START
    proceeds with elapsed=0 and logs a warning."""
    exp = _create_chain(client, auth_headers, name="IncompletePred")
    # Wash is still PENDING/READY -- never completed.
    _force_ready("reincubate")
    with caplog.at_level(logging.WARNING):
        r = client.post("/api/steps/reincubate/start", headers=auth_headers)
    assert r.status_code == 200, r.get_json()
    re = next(s for s in r.get_json()["steps"] if s["id"] == "reincubate")
    assert re["status"] == StepStatus.RUNNING.value
    # No seed -- elapsed_seconds is omitted from payload OR is 0.
    assert re.get("elapsed_seconds", 0) == pytest.approx(0.0, abs=0.5)
    # Warning about "not completed yet" surfaced.
    assert any(
        "not completed yet" in msg or "has not completed" in msg
        for msg in (rec.getMessage() for rec in caplog.records)
    ), f"expected 'not completed' warning, got log: {[rec.getMessage() for rec in caplog.records]}"


# ---------------------------------------------------------------------------
# 4. Edge case: first step in condition with "previous" -> no-op.
# ---------------------------------------------------------------------------
def test_first_step_in_condition_with_previous_no_ops(client, auth_headers, caplog):
    """A step is the FIRST in its Condition (no predecessor) but still has
    ``inherits_elapsed_from = "previous"``. START proceeds with elapsed=0."""
    payload = {
        "name": "FirstStepInherit",
        "conditions": [
            {"id": "cA", "name": "A", "color": "slate", "order_index": 0},
        ],
        "steps": [
            {
                "id": "lone",
                "name": "Lone",
                "step_type": "fixed_duration",
                "duration_seconds": 600,
                "condition_id": "cA",
                "inherits_elapsed_from": "previous",
            },
        ],
    }
    r = client.post("/api/experiments", headers=auth_headers, json=payload)
    assert r.status_code == 201, r.get_json()

    _force_ready("lone")
    with caplog.at_level(logging.WARNING):
        r = client.post("/api/steps/lone/start", headers=auth_headers)
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    s = next(s for s in body["steps"] if s["id"] == "lone")
    assert s["status"] == StepStatus.RUNNING.value
    assert s.get("elapsed_seconds", 0) == pytest.approx(0.0, abs=0.5)
    # Warning surfaced about no preceding sibling.
    assert any(
        "no preceding" in rec.getMessage().lower()
        or "previous" in rec.getMessage().lower()
        for rec in caplog.records
    )


# ---------------------------------------------------------------------------
# 5. Edge case: cross-condition step-id reference -> warn + skip.
# ---------------------------------------------------------------------------
def test_cross_condition_inherit_reference_ignored(client, auth_headers, caplog):
    """``inherits_elapsed_from = <step_id_in_other_condition>`` is rejected at
    resolution time: warn + proceed with elapsed=0."""
    payload = {
        "name": "CrossCondInherit",
        "conditions": [
            {"id": "cA", "name": "A", "color": "coral", "order_index": 0},
            {"id": "cB", "name": "B", "color": "teal", "order_index": 1},
        ],
        "steps": [
            {
                "id": "stepA",
                "name": "stepA",
                "step_type": "fixed_duration",
                "duration_seconds": 100,
                "condition_id": "cA",
            },
            {
                "id": "stepB",
                "name": "stepB",
                "step_type": "fixed_duration",
                "duration_seconds": 600,
                "condition_id": "cB",
                # CROSS-CONDITION reference. Resolution should skip the inherit.
                "inherits_elapsed_from": "stepA",
            },
        ],
    }
    r = client.post("/api/experiments", headers=auth_headers, json=payload)
    assert r.status_code == 201, r.get_json()

    # Complete stepA so the source HAS final elapsed -- this isolates the
    # cross-condition rejection from the "incomplete predecessor" path.
    _force_complete("stepA", elapsed_seconds=100)

    _force_ready("stepB")
    with caplog.at_level(logging.WARNING):
        r = client.post("/api/steps/stepB/start", headers=auth_headers)
    assert r.status_code == 200, r.get_json()
    b = next(s for s in r.get_json()["steps"] if s["id"] == "stepB")
    assert b["status"] == StepStatus.RUNNING.value
    assert b.get("elapsed_seconds", 0) == pytest.approx(0.0, abs=0.5)
    # Cross-condition warning surfaced.
    assert any(
        "different condition" in rec.getMessage().lower()
        or "cross" in rec.getMessage().lower()
        for rec in caplog.records
    )


# ---------------------------------------------------------------------------
# 6. Integration: restart preserves the seeded elapsed_seconds for a RUNNING step.
# ---------------------------------------------------------------------------
def test_restart_preserves_seeded_elapsed_for_running_step(client, auth_headers):
    """After START seeds elapsed and the step is RUNNING, a scheduler cache
    rebuild (simulating a process restart) preserves elapsed_seconds via
    StepORM.apply_dataclass."""
    import main as main_module
    from models import StepORM
    from db import db

    exp = _create_chain(client, auth_headers, name="RestartPreservesSeed")

    _force_complete("wash", elapsed_seconds=240)
    _force_ready("reincubate")
    r = client.post("/api/steps/reincubate/start", headers=auth_headers)
    assert r.status_code == 200, r.get_json()

    # Simulate restart: drop and rehydrate the scheduler cache.
    with main_module.app.app_context():
        main_module.scheduler.reset_cache()
        main_module.scheduler.hydrate_from_db()
        re = main_module.scheduler.get_step("reincubate")
        assert re is not None
        assert re.status == StepStatus.RUNNING
        # The seeded elapsed survived. Allow a small fudge for the wall-clock
        # tick that handle_step_start adds (it sets actual_start_time = now,
        # but elapsed_seconds was set BEFORE start() ran, so it's the seed).
        assert re.elapsed_time.total_seconds() == pytest.approx(240.0, abs=0.5)
        # The directive itself round-trips so a future re-start would re-seed.
        assert re.inherits_elapsed_from == "previous"

        # Verify the ORM row has the directive too.
        row = db.session.get(StepORM, "reincubate")
        assert row is not None
        assert row.inherits_elapsed_from == "previous"
        assert row.elapsed_seconds == pytest.approx(240.0, abs=0.5)
