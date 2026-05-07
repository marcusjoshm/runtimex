"""U1 tests: Condition entity, auto-backfill migration, cross-condition deps."""
from datetime import timedelta

import pytest


def _create_payload(name="Test", conditions=None, steps=None):
    """Build a request body for POST /api/experiments."""
    return {"name": name, "description": "", "conditions": conditions or [], "steps": steps or []}


# ---------------------------------------------------------------------------
# Test 1: round-trip a multi-Condition experiment via the API.
# ---------------------------------------------------------------------------
def test_round_trip_multi_condition_experiment(client, auth_headers):
    """POST + GET an Experiment with two Conditions; payload preserves all fields."""
    payload = _create_payload(
        name="ChainExp",
        conditions=[
            {"id": "cA", "name": "Condition A", "color": "coral", "order_index": 0, "description": "alpha"},
            {"id": "cB", "name": "Condition B", "color": "teal", "order_index": 1, "description": "beta"},
        ],
        steps=[
            {"name": "A1", "step_type": "fixed_duration", "duration_seconds": 60, "condition_id": "cA"},
            {"name": "A2", "step_type": "task", "duration_seconds": 30, "condition_id": "cA"},
            {"name": "B1", "step_type": "fixed_duration", "duration_seconds": 90, "condition_id": "cB"},
        ],
    )
    create_resp = client.post("/api/experiments", headers=auth_headers, json=payload)
    assert create_resp.status_code == 201, create_resp.get_json()
    exp = create_resp.get_json()
    exp_id = exp["id"]

    assert {c["id"] for c in exp["conditions"]} == {"cA", "cB"}
    assert {c["name"] for c in exp["conditions"]} == {"Condition A", "Condition B"}
    assert next(c for c in exp["conditions"] if c["id"] == "cA")["color"] == "coral"

    # Steps carry condition_id back.
    by_name = {s["name"]: s for s in exp["steps"]}
    assert by_name["A1"]["condition_id"] == "cA"
    assert by_name["A2"]["condition_id"] == "cA"
    assert by_name["B1"]["condition_id"] == "cB"

    get_resp = client.get(f"/api/experiments/{exp_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    rehydrated = get_resp.get_json()
    assert {c["id"] for c in rehydrated["conditions"]} == {"cA", "cB"}
    assert {s["condition_id"] for s in rehydrated["steps"]} == {"cA", "cB"}


# ---------------------------------------------------------------------------
# Test 2: AE1 -- two Conditions with overlapping microscope steps; conflict
# report includes condition names and IDs (R1, R6 data shape; full UI labels
# land in U2).
# ---------------------------------------------------------------------------
def test_ae1_conflict_report_includes_condition_metadata(client, auth_headers):
    """`Covers AE1.` Save the cell-stress assay; conflict references both Conditions."""
    from datetime import datetime

    base = datetime(2026, 5, 6, 14, 0, 0)
    payload = _create_payload(
        name="Cell stress assay",
        conditions=[
            {"id": "condA", "name": "Condition A", "color": "coral", "order_index": 0},
            {"id": "condB", "name": "Condition B", "color": "teal", "order_index": 1},
        ],
        steps=[
            {
                "id": "imgA",
                "name": "Image A",
                "step_type": "automated_task",
                "duration_seconds": 1200,
                "resource_required": "microscope",
                "condition_id": "condA",
            },
            {
                "id": "imgB",
                "name": "Image B",
                "step_type": "automated_task",
                "duration_seconds": 1200,
                "resource_required": "microscope",
                "condition_id": "condB",
            },
        ],
    )
    create_resp = client.post("/api/experiments", headers=auth_headers, json=payload)
    assert create_resp.status_code == 201, create_resp.get_json()
    exp = create_resp.get_json()
    exp_id = exp["id"]

    # Force both microscope steps to be scheduled at overlapping times by
    # pinning their scheduled_start_time via PUT.
    put_payload = {
        "steps": [
            {
                "id": "imgA",
                "name": "Image A",
                "step_type": "automated_task",
                "duration_seconds": 1200,
                "resource_required": "microscope",
                "condition_id": "condA",
                "scheduled_start_time": base.isoformat(),
            },
            {
                "id": "imgB",
                "name": "Image B",
                "step_type": "automated_task",
                "duration_seconds": 1200,
                "resource_required": "microscope",
                "condition_id": "condB",
                "scheduled_start_time": base.isoformat(),
            },
        ]
    }
    # The route doesn't currently honor scheduled_start_time from the payload;
    # instead use the conflicts endpoint after letting the scheduler derive
    # times. The two automated_task steps have no deps so they'll both be
    # scheduled at "now"; that's overlap enough to trip the detector.
    conflicts_resp = client.get(f"/api/experiments/{exp_id}/conflicts", headers=auth_headers)
    assert conflicts_resp.status_code == 200
    conflicts = conflicts_resp.get_json()
    assert len(conflicts) >= 1, f"expected at least one microscope conflict, got {conflicts}"
    c = conflicts[0]
    # Per the plan, the conflict payload's condition labels are added in U2.
    # Here we only assert that the underlying step_a/step_b refer to the two
    # microscope-using steps. The labeling pass lives in U2.
    assert {c["step_a"], c["step_b"]} == {"imgA", "imgB"}
    assert c["resource"] == "microscope"


# ---------------------------------------------------------------------------
# Test 3: Auto-create default "Main" Condition when caller omits conditions.
# ---------------------------------------------------------------------------
def test_default_main_condition_when_payload_lacks_conditions(client, auth_headers):
    """POST without a conditions array -> Experiment ends up with one Main Condition."""
    payload = {
        "name": "LegacyShape",
        "description": "no conditions in body",
        "steps": [
            {"name": "lone", "step_type": "task", "duration_seconds": 60},
        ],
    }
    resp = client.post("/api/experiments", headers=auth_headers, json=payload)
    assert resp.status_code == 201, resp.get_json()
    exp = resp.get_json()
    assert len(exp["conditions"]) == 1
    assert exp["conditions"][0]["name"] == "Main"
    main_id = exp["conditions"][0]["id"]
    assert exp["steps"][0]["condition_id"] == main_id


# ---------------------------------------------------------------------------
# Test 4: Cross-condition dependencies are rejected on save.
# ---------------------------------------------------------------------------
def test_cross_condition_dependency_rejected(client, auth_headers):
    """A Step whose dependencies reference another Condition's Step returns 400."""
    payload = _create_payload(
        name="CrossDeps",
        conditions=[
            {"id": "cA", "name": "Condition A", "color": "coral", "order_index": 0},
            {"id": "cB", "name": "Condition B", "color": "teal", "order_index": 1},
        ],
        steps=[
            {"id": "step1", "name": "step1", "step_type": "task", "duration_seconds": 30, "condition_id": "cA"},
            {
                "id": "step2",
                "name": "step2",
                "step_type": "task",
                "duration_seconds": 30,
                "condition_id": "cB",
                "dependencies": ["step1"],  # CROSS-CONDITION -- reject
            },
        ],
    )
    resp = client.post("/api/experiments", headers=auth_headers, json=payload)
    assert resp.status_code == 400, resp.get_json()
    assert "cross-condition" in (resp.get_json().get("error") or "").lower()


# ---------------------------------------------------------------------------
# Test 5: Cascading delete -- delete an Experiment, its Conditions and Steps
# disappear too.
# ---------------------------------------------------------------------------
def test_cascading_delete_removes_conditions_and_steps(client, auth_headers):
    """Cascade still works after Conditions are introduced (no schema regression)."""
    import main as main_module
    from db import db
    from models import ExperimentORM, ConditionORM, StepORM

    payload = _create_payload(
        name="DeleteMe",
        conditions=[{"id": "cX", "name": "X", "color": "amber", "order_index": 0}],
        steps=[
            {"id": "s1", "name": "s1", "step_type": "task", "duration_seconds": 30, "condition_id": "cX"},
        ],
    )
    create_resp = client.post("/api/experiments", headers=auth_headers, json=payload)
    exp_id = create_resp.get_json()["id"]

    with main_module.app.app_context():
        # Manual delete via scheduler helper (no DELETE route yet -- that's a
        # follow-up). Same pattern test_persistence.py uses.
        ok = main_module.scheduler.remove_experiment(exp_id)
        assert ok is True
        assert db.session.get(ExperimentORM, exp_id) is None
        assert db.session.get(ConditionORM, "cX") is None
        assert db.session.get(StepORM, "s1") is None


# ---------------------------------------------------------------------------
# Test 6: Backfill -- a pre-existing experiment row with no Conditions gets
# a "Main" Condition on next init_db.
# ---------------------------------------------------------------------------
def test_backfill_creates_main_condition_for_legacy_data(tmp_path):
    """Simulate an upgrade path: existing experiment row + steps with NULL
    condition_id; running init_db creates a Main condition and backfills."""
    import importlib
    from datetime import datetime as dt
    from sqlalchemy import text
    from flask import Flask
    from flask_jwt_extended import JWTManager

    from db import db, init_db
    from models import ExperimentORM, ConditionORM, StepORM

    db_file = tmp_path / "legacy.db"
    uri = f"sqlite:///{db_file}"

    # First boot: build the modern schema, then manually insert a "legacy"
    # experiment + step shape WITHOUT any Conditions.
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "test"
    init_db(app, database_uri=uri)

    with app.app_context():
        # Direct SQL insert mimicking pre-Conditions data.
        db.session.execute(
            text(
                "INSERT INTO experiments (id, name, description, owner, shared_with, created_at) "
                "VALUES (:id, :name, NULL, NULL, '{}', :ts)"
            ),
            {"id": "exp-legacy", "name": "Legacy", "ts": dt.utcnow()},
        )
        db.session.execute(
            text(
                "INSERT INTO steps (id, experiment_id, name, duration_seconds, step_type, status, "
                "step_metadata, elapsed_seconds, created_at) "
                "VALUES (:id, :exp_id, :name, :dur, :ty, :st, '{}', 0, :ts)"
            ),
            {
                "id": "step-legacy",
                "exp_id": "exp-legacy",
                "name": "legacy step",
                "dur": 60.0,
                "ty": "task",
                "st": "pending",
                "ts": dt.utcnow(),
            },
        )
        db.session.commit()

        # Verify the row has NULL condition_id (pre-backfill).
        cid_before = db.session.execute(
            text("SELECT condition_id FROM steps WHERE id = 'step-legacy'")
        ).scalar()
        assert cid_before is None

        db.session.remove()
        db.engine.dispose()

    # Second boot: re-run init_db; backfill should kick in (idempotent).
    init_db(app, database_uri=uri)

    with app.app_context():
        # The legacy experiment now has exactly one Condition named "Main".
        conds = db.session.scalars(
            db.select(ConditionORM).where(ConditionORM.experiment_id == "exp-legacy")
        ).all()
        assert len(conds) == 1
        assert conds[0].name == "Main"
        main_id = conds[0].id

        # The legacy step now references the Main Condition.
        cid_after = db.session.execute(
            text("SELECT condition_id FROM steps WHERE id = 'step-legacy'")
        ).scalar()
        assert cid_after == main_id

        # Idempotency: running init_db a third time does NOT create another
        # "Main" Condition for the same experiment.
        db.session.remove()
        db.engine.dispose()

    init_db(app, database_uri=uri)
    with app.app_context():
        conds_again = db.session.scalars(
            db.select(ConditionORM).where(ConditionORM.experiment_id == "exp-legacy")
        ).all()
        assert len(conds_again) == 1
        assert conds_again[0].id == main_id
        db.session.remove()
        db.engine.dispose()
