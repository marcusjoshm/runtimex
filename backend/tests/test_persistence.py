"""Persistence tests for U2.

Most tests reuse the in-memory ``client`` fixture from conftest. Tests that
need to simulate a process restart (load the same DB from disk in a fresh
app context) build a throwaway Flask app pointed at a tmp_path SQLite file.
"""
from datetime import timedelta

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager


def _build_isolated_app(database_uri: str):
    """Build a fresh Flask + SQLAlchemy app pointed at ``database_uri``.

    Mirrors the production setup just enough to register/login/CRUD via the
    auth + experiment routes. Used to simulate a restart for the file-backed
    SQLite tests.
    """
    # Late imports so every call gets fresh module state.
    from db import db, init_db
    import auth as auth_module
    from notifications import NotificationService
    from scheduler import Scheduler
    from models import (
        Experiment,
        Step,
        StepStatus,
        StepType,
        ExperimentORM,
    )

    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "test-secret-key"
    app.config["TESTING"] = True
    JWTManager(app)
    init_db(app, database_uri=database_uri)
    get_user = auth_module.register_auth_routes(app, None)
    scheduler = Scheduler()
    with app.app_context():
        scheduler.hydrate_from_db()

    # Bare-bones experiment routes for the restart tests. We don't need every
    # production route here -- just enough to round-trip experiments.
    @app.route('/api/experiments/<eid>', methods=['GET'])
    def _get_experiment(eid):
        from flask import jsonify
        with app.app_context():
            orm = db.session.get(ExperimentORM, eid)
        if orm is None:
            return jsonify({'error': 'not found'}), 404
        exp = orm.to_dataclass()
        return jsonify({
            'id': exp.id,
            'name': exp.name,
            'description': exp.description,
            'steps': [
                {
                    'id': s.id,
                    'name': s.name,
                    'duration_seconds': s.duration.total_seconds(),
                    'status': s.status.value,
                    'dependencies': s.dependencies,
                    'resource_required': s.resource_needed,
                }
                for s in exp.steps.values()
            ],
        })

    return app, scheduler, get_user


# ---------------------------------------------------------------------------
# Test 1: user persistence across simulated restart (file-backed SQLite)
# ---------------------------------------------------------------------------
def test_user_persists_across_restart(tmp_path):
    db_file = tmp_path / "runtimex-restart.db"
    uri = f"sqlite:///{db_file}"

    # First boot -- register a user.
    app1, _, _ = _build_isolated_app(uri)
    with app1.test_client() as c1:
        r = c1.post(
            '/api/auth/register',
            json={'username': 'persistuser', 'email': 'pu@example.com', 'password': 'pw12345'},
        )
        assert r.status_code == 201, r.get_json()

    # Tear down: close all SQLAlchemy connections so SQLite releases the file.
    from db import db
    with app1.app_context():
        db.session.remove()
        db.engine.dispose()

    # Second boot -- same DB file, fresh app context. Login should succeed.
    app2, _, _ = _build_isolated_app(uri)
    with app2.test_client() as c2:
        r = c2.post(
            '/api/auth/login',
            json={'username': 'persistuser', 'password': 'pw12345'},
        )
        assert r.status_code == 200, r.get_json()
        assert r.get_json()['token']

    with app2.app_context():
        db.session.remove()
        db.engine.dispose()


# ---------------------------------------------------------------------------
# Test 2: experiment + steps + dependencies survive restart
# ---------------------------------------------------------------------------
def test_experiment_with_dependencies_survives_restart(tmp_path):
    from datetime import timedelta as td
    from db import db
    from models import Experiment, Step, StepType, ExperimentORM

    db_file = tmp_path / "runtimex-exp-restart.db"
    uri = f"sqlite:///{db_file}"

    # First boot: create an experiment with 3 steps, where step C depends on B,
    # and B depends on A.
    app1, scheduler1, _ = _build_isolated_app(uri)
    with app1.app_context():
        exp = Experiment(name="ChainExp", description="A->B->C")
        exp.owner = "creator"
        exp.shared_with = {}
        a = Step(name="A", duration=td(minutes=10), step_type=StepType.FIXED_DURATION)
        b = Step(name="B", duration=td(minutes=20), step_type=StepType.FIXED_DURATION)
        c = Step(name="C", duration=td(minutes=15), step_type=StepType.FIXED_DURATION)
        b.dependencies = [a.id]
        c.dependencies = [b.id]
        exp.add_step(a)
        exp.add_step(b)
        exp.add_step(c)
        scheduler1.add_experiment(exp)

        exp_id = exp.id
        a_id, b_id, c_id = a.id, b.id, c.id

    with app1.app_context():
        db.session.remove()
        db.engine.dispose()

    # Second boot: rehydrate and check structure.
    app2, scheduler2, _ = _build_isolated_app(uri)
    with app2.app_context():
        rehydrated = scheduler2.experiments.get(exp_id)
        assert rehydrated is not None
        assert len(rehydrated.steps) == 3
        # Validate dependency relationships round-tripped.
        b_dc = rehydrated.steps[b_id]
        c_dc = rehydrated.steps[c_id]
        assert b_dc.dependencies == [a_id]
        assert c_dc.dependencies == [b_id]
        # Names + durations.
        assert rehydrated.steps[a_id].name == "A"
        assert rehydrated.steps[b_id].duration == td(minutes=20)

    with app2.app_context():
        db.session.remove()
        db.engine.dispose()


# ---------------------------------------------------------------------------
# Test 3: PUT preserves RUNNING step state (regression for wipe-and-recreate)
# ---------------------------------------------------------------------------
def test_put_preserves_running_step_state(client, auth_headers):
    """Create experiment -> start a step -> PUT renames it -> running state unchanged."""
    # Create an experiment with two steps.
    create_resp = client.post(
        '/api/experiments',
        headers=auth_headers,
        json={
            'name': 'ConcurrentExp',
            'description': 'should preserve in-flight state',
            'steps': [
                {'name': 'StepOne', 'duration': 5, 'type': 'task', 'dependencies': []},
                {'name': 'StepTwo', 'duration': 10, 'type': 'task', 'dependencies': []},
            ],
        },
    )
    assert create_resp.status_code == 201, create_resp.get_json()
    exp = create_resp.get_json()
    exp_id = exp['id']
    step_one_id = exp['steps'][0]['id']
    step_two_id = exp['steps'][1]['id']

    # Force step one to RUNNING via the scheduler. (We can't rely on the start
    # route because READY status isn't guaranteed for non-dep steps in the
    # current scheduler -- they go straight to PENDING. Mutate the dataclass
    # via the scheduler's helper which also persists.)
    import main as main_module
    from models import StepStatus
    from datetime import datetime as dt
    with main_module.app.app_context():
        step = main_module.scheduler.get_step(step_one_id)
        # Bypass the READY check so the test is deterministic.
        step.status = StepStatus.READY
        main_module.scheduler.handle_step_start(step_one_id)
        running_started_at = step.actual_start_time
    assert running_started_at is not None

    # PUT the experiment with a name change. Pass step IDs so the upsert path
    # finds them.
    put_resp = client.put(
        f'/api/experiments/{exp_id}',
        headers=auth_headers,
        json={
            'name': 'ConcurrentExp Renamed',
            'description': 'updated',
            'steps': [
                {'id': step_one_id, 'name': 'StepOne Renamed', 'duration': 5, 'type': 'task'},
                {'id': step_two_id, 'name': 'StepTwo', 'duration': 10, 'type': 'task'},
            ],
        },
    )
    assert put_resp.status_code == 200, put_resp.get_json()

    # Step one should still be RUNNING, with its actual_start_time intact.
    with main_module.app.app_context():
        from models import StepORM
        from db import db
        step_one_orm = db.session.get(StepORM, step_one_id)
        assert step_one_orm is not None, "step row was wiped by PUT"
        assert step_one_orm.status == StepStatus.RUNNING.value, (
            f"expected RUNNING, got {step_one_orm.status}"
        )
        assert step_one_orm.actual_start_time is not None
        # Editable fields did update.
        assert step_one_orm.name == 'StepOne Renamed'

    # Cache is also consistent.
    with main_module.app.app_context():
        cached = main_module.scheduler.get_step(step_one_id)
        assert cached.status == StepStatus.RUNNING


# ---------------------------------------------------------------------------
# Test 4: Cascade delete -- removing the experiment removes its steps.
# ---------------------------------------------------------------------------
def test_cascade_delete_removes_steps(client, auth_headers):
    create_resp = client.post(
        '/api/experiments',
        headers=auth_headers,
        json={
            'name': 'DoomedExp',
            'steps': [
                {'name': 'StepX', 'duration': 5, 'type': 'task'},
                {'name': 'StepY', 'duration': 7, 'type': 'task'},
            ],
        },
    )
    assert create_resp.status_code == 201, create_resp.get_json()
    exp = create_resp.get_json()
    exp_id = exp['id']
    step_ids = [s['id'] for s in exp['steps']]

    import main as main_module
    from models import ExperimentORM, StepORM
    from db import db
    with main_module.app.app_context():
        for sid in step_ids:
            assert db.session.get(StepORM, sid) is not None

        # Delete via the scheduler helper (no DELETE route exists in U2 scope;
        # U3 is where ownership-checked delete will be added).
        ok = main_module.scheduler.remove_experiment(exp_id)
        assert ok is True

        assert db.session.get(ExperimentORM, exp_id) is None
        for sid in step_ids:
            assert db.session.get(StepORM, sid) is None


# ---------------------------------------------------------------------------
# Test 5: Notification round-trip across restart.
# ---------------------------------------------------------------------------
def test_notification_round_trip_across_restart(tmp_path):
    from db import db
    from notifications import (
        NotificationService,
        Notification,
        NotificationType,
        NotificationPriority,
    )
    from models import User, UserORM

    db_file = tmp_path / "runtimex-notif.db"
    uri = f"sqlite:///{db_file}"

    app1, _, _ = _build_isolated_app(uri)
    svc1 = NotificationService(socketio=None)
    with app1.app_context():
        # Create a user row so the FK on NotificationORM.target_user resolves.
        u = User(username='notifuser', email='nu@example.com', password='pw')
        db.session.add(UserORM.from_dataclass(u))
        db.session.commit()

        n = Notification(
            title='Hello',
            message='Round-trip me',
            notification_type=NotificationType.GENERAL_INFO,
            priority=NotificationPriority.LOW,
            target_users=['notifuser'],
        )
        nid = svc1.add_notification(n)

    with app1.app_context():
        db.session.remove()
        db.engine.dispose()

    app2, _, _ = _build_isolated_app(uri)
    svc2 = NotificationService(socketio=None)
    with app2.app_context():
        rows = svc2.get_user_notifications('notifuser')
        assert len(rows) == 1
        assert rows[0].id == nid
        assert rows[0].title == 'Hello'
        assert rows[0].message == 'Round-trip me'
        assert rows[0].target_users == ['notifuser']

    with app2.app_context():
        db.session.remove()
        db.engine.dispose()


# ---------------------------------------------------------------------------
# Test 6: empty resource_required doesn't break persistence.
# ---------------------------------------------------------------------------
def test_step_with_no_resource_persists(client, auth_headers):
    create_resp = client.post(
        '/api/experiments',
        headers=auth_headers,
        json={
            'name': 'NoResourceExp',
            'steps': [
                {'name': 'PlainStep', 'duration': 5, 'type': 'fixed_duration'},
                {'name': 'EmptyResourceStep', 'duration': 3, 'type': 'fixed_duration', 'resourceNeeded': ''},
            ],
        },
    )
    assert create_resp.status_code == 201, create_resp.get_json()
    exp = create_resp.get_json()

    import main as main_module
    from models import StepORM
    from db import db
    with main_module.app.app_context():
        for s in exp['steps']:
            row = db.session.get(StepORM, s['id'])
            assert row is not None
            # Either None or '' is acceptable for "no resource".
            assert row.resource_needed in (None, '')
