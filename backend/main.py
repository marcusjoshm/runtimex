from datetime import datetime, timedelta
import json
import logging
import os
import tempfile
import uuid

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from flask_socketio import SocketIO, join_room
from flask_jwt_extended import (
    JWTManager,
    jwt_required,
    get_jwt_identity,
    verify_jwt_in_request,
)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from db import db, init_db
from models import (
    Experiment,
    Step,
    StepStatus,
    StepType,
    ExperimentORM,
    StepORM,
    TemplateORM,
    UserORM,
)
from scheduler import Scheduler
import auth
from permissions import (
    can_view_experiment,
    can_edit_experiment,
    can_run_step,
)
from serializers import experiment_to_dict, step_to_dict, template_steps_payload

# Import notification system
from notifications import NotificationService, Notification, NotificationType, NotificationPriority, ActionType, NotificationAction, create_notification_factories

logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# Global scheduler instance to maintain state
scheduler = Scheduler()

_JWT_DEV_FALLBACK = "dev-only-insecure-secret-do-not-use-in-production"
jwt_secret = os.environ.get("JWT_SECRET_KEY")
if not jwt_secret:
    logger.warning(
        "JWT_SECRET_KEY not set in environment; using insecure dev fallback. "
        "Set JWT_SECRET_KEY before deploying."
    )
    jwt_secret = _JWT_DEV_FALLBACK
app.config["JWT_SECRET_KEY"] = jwt_secret
jwt = JWTManager(app)

# Initialize SQLAlchemy + create tables. Must run before any route handler
# that issues a query (auth routes call UserORM.query at request time).
init_db(app)

# Initialize auth routes and get the user getter function
get_user = auth.register_auth_routes(app, jwt)

# Hydrate the scheduler cache from DB so existing experiments survive restart.
with app.app_context():
    try:
        scheduler.hydrate_from_db()
    except Exception as e:
        logger.warning("Scheduler hydration skipped: %s", e)

# Initialize notification service with socketio
notification_service = NotificationService(socketio)

# Create notification factories
notification_factories = create_notification_factories(scheduler)

# --- Define Helper Function to Print Schedule --- 
def print_schedule(scheduler: Scheduler):
    print("\n--- Current Schedule ---")
    # Sort steps by scheduled start time for readability
    sorted_steps = sorted(
        scheduler.schedule.values(),
        key=lambda s: s.scheduled_start_time or datetime.max
    )
    for step in sorted_steps:
        start = step.scheduled_start_time.strftime("%H:%M:%S") if step.scheduled_start_time else "Not Scheduled"
        end = step.scheduled_end_time.strftime("%H:%M:%S") if step.scheduled_end_time else "Not Scheduled"
        actual_start = step.actual_start_time.strftime("%H:%M:%S") if step.actual_start_time else "N/A"
        actual_end = step.actual_end_time.strftime("%H:%M:%S") if step.actual_end_time else "N/A"
        print(
            f"- {step.name:<20} | Status: {step.status.value:<10} | Type: {step.step_type.value:<15} | Scheduled: {start} - {end} | Actual: {actual_start} - {actual_end}"
        )
    print("------------------------\n")

# --- API Routes ---

@app.route('/api/experiments', methods=['GET'])
@jwt_required()
def get_experiments():
    """List experiments visible to the requesting user (own + shared).

    Behavior change vs. pre-U3: this endpoint used to return *all* experiments
    in the system. It now scopes to the current user's view set. The Home
    page already uses `/api/user/experiments` for "my" experiments, so the
    semantic change is consistent with how the frontend consumes this route.
    """
    username = get_jwt_identity()
    user = get_user(username) if username else None
    experiments = [
        experiment_to_dict(exp)
        for exp in scheduler.experiments.values()
        if can_view_experiment(user, exp)
    ]
    return jsonify(experiments)

@app.route('/api/experiments/<experiment_id>', methods=['GET'])
@jwt_required()
def get_experiment(experiment_id):
    """Fetch a single experiment.

    Existence-privacy: if the user lacks view permission we return 404, not
    403. That keeps an attacker from probing experiment IDs to confirm they
    exist.
    """
    username = get_jwt_identity()
    user = get_user(username) if username else None

    experiment = scheduler.experiments.get(experiment_id)
    if not experiment or not can_view_experiment(user, experiment):
        return jsonify({'error': 'Experiment not found'}), 404

    return jsonify(experiment_to_dict(experiment))

def _step_from_payload(step_data: dict) -> Step:
    """Build a ``Step`` from an incoming JSON payload.

    Reads the snake_case wire format normalized in U8:
      * ``duration_seconds`` (float seconds) -- previously ``duration`` (int minutes).
      * ``step_type`` -- previously ``type``.
      * ``resource_required`` -- previously ``resourceNeeded``.

    The duration is parsed as a float so sub-second precision survives the
    round-trip (the audit's ``// 60`` truncation bug was the symptom of
    treating duration as integer minutes).
    """
    duration_seconds = float(step_data.get('duration_seconds', 0) or 0)
    return Step(
        name=step_data['name'],
        duration=timedelta(seconds=duration_seconds),
        step_type=StepType(step_data.get('step_type', 'fixed_duration')),
        dependencies=step_data.get('dependencies', []),
        notes=step_data.get('notes'),
        resource_needed=step_data.get('resource_required'),
    )


@app.route('/api/experiments', methods=['POST'])
@jwt_required()
def create_experiment():
    # Create a new experiment
    data = request.json
    username = get_jwt_identity()

    experiment = Experiment(
        name=data['name'],
        description=data.get('description', '')
    )

    # Add ownership information
    experiment.owner = username
    experiment.shared_with = {}  # username -> permission

    for step_data in data.get('steps', []):
        step = _step_from_payload(step_data)
        experiment.add_step(step)

    scheduler.add_experiment(experiment)

    if experiment.steps:
        start_time = datetime.now()
        scheduler.calculate_initial_schedule(start_time=start_time)

    return jsonify(experiment_to_dict(experiment)), 201

@app.route('/api/experiments/<experiment_id>', methods=['PUT'])
@jwt_required()
def update_experiment(experiment_id):
    """Update an experiment, preserving in-flight step state.

    Replaces the previous wipe-and-recreate behaviour (which lost RUNNING
    step status + actual_start_time on every save). Steps are upserted by
    ID: surviving IDs keep their runtime state; missing IDs are removed;
    new IDs are added.

    Permission policy (U3): users without view perms get 404 (existence
    privacy); users with view-only get 403 with "edit permission required".
    """
    username = get_jwt_identity()
    user = get_user(username) if username else None

    experiment = scheduler.experiments.get(experiment_id)
    if not experiment or not can_view_experiment(user, experiment):
        return jsonify({'error': 'Experiment not found'}), 404
    if not can_edit_experiment(user, experiment):
        return jsonify({'error': 'edit permission required'}), 403

    data = request.json or {}

    # Update basic info
    experiment.name = data.get('name', experiment.name)
    experiment.description = data.get('description', experiment.description)

    if 'steps' in data:
        # Build a list of incoming Step objects. If the client sends an `id`
        # we honor it (used by existing-step edits); otherwise we mint a new
        # one (treated as a brand-new step).
        incoming = []
        for step_data in data['steps']:
            new_step = _step_from_payload(step_data)
            if step_data.get('id'):
                new_step.id = step_data['id']
            incoming.append(new_step)

        scheduler.upsert_experiment_steps(experiment, incoming)

        # Recalculate schedule for any newly-added (PENDING) steps. Existing
        # RUNNING/COMPLETED steps are skipped by calculate_initial_schedule.
        start_time = datetime.now()
        scheduler.calculate_initial_schedule(start_time=start_time)

    # Persist top-level field updates (name, description) too.
    exp_orm = db.session.get(ExperimentORM, experiment.id)
    if exp_orm is not None:
        exp_orm.name = experiment.name
        exp_orm.description = experiment.description
        db.session.commit()

    # Surface conflicts on save so the Designer can warn without an extra
    # round-trip. We also fan out one ``resource_conflict`` notification per
    # detected pair to the experiment's owner (U7). Notifications go to the
    # owner only; share-recipients are intentionally out of scope here and
    # tracked as a deferred follow-up.
    conflicts = Scheduler.check_for_conflicts(experiment)
    _emit_resource_conflict_notifications(experiment, conflicts)
    payload = experiment_to_dict(experiment)
    payload["conflicts"] = conflicts
    return jsonify(payload)

@app.route('/api/experiments/<experiment_id>/conflicts', methods=['GET'])
@jwt_required()
def get_experiment_conflicts(experiment_id):
    """Return the resource-conflict list for one experiment.

    Existence-privacy mirrors ``get_experiment``: an unrelated user gets 404
    rather than 403 so they can't probe IDs to confirm membership.

    The payload shape matches what ``Scheduler.check_for_conflicts`` returns
    in-process, so the round-trip equals the local call (validated by tests).
    Notifications for these conflicts land in U7 -- this route is a pure read.
    """
    username = get_jwt_identity()
    user = get_user(username) if username else None

    experiment = scheduler.experiments.get(experiment_id)
    if not experiment or not can_view_experiment(user, experiment):
        return jsonify({'error': 'Experiment not found'}), 404

    return jsonify(Scheduler.check_for_conflicts(experiment))


def _find_experiment_for_step(step_id):
    """Locate the experiment that owns a step. Helper for step-state routes."""
    for exp in scheduler.experiments.values():
        if step_id in exp.steps:
            return exp
    return None


def _authorize_step_transition(step_id):
    """Resolve (step, experiment, error_response) for a step-state mutation.

    Returns ``(step, experiment, None)`` on success or
    ``(None, None, (json, status))`` on auth/permission/not-found failure.

    Existence-privacy: if the user can't view the parent experiment, we
    pretend the step doesn't exist (404), regardless of whether it actually
    does. View-but-not-edit returns 403 with the documented error shape.
    """
    username = get_jwt_identity()
    user = get_user(username) if username else None

    step = scheduler.get_step(step_id)
    experiment = _find_experiment_for_step(step_id) if step else None

    if not step or not experiment or not can_view_experiment(user, experiment):
        return None, None, (jsonify({'error': 'Step not found'}), 404)
    if not can_run_step(user, step, experiment):
        return None, None, (jsonify({'error': 'edit permission required'}), 403)
    return step, experiment, None


def _emit_experiment_update(experiment):
    """Push the latest experiment snapshot to every connected client.

    All step-transition routes call this after a successful mutation so any
    open Runner / WatchView re-renders without polling. The payload shape
    matches the REST GET response, so frontend handlers don't need to branch.
    """
    try:
        socketio.emit('experiment_update', experiment_to_dict(experiment))
    except Exception as exc:
        logger.warning("experiment_update emit failed: %s", exc)


def _snapshot_step_statuses(experiment):
    """Capture {step_id: status} so we can detect newly-READY steps post-update."""
    return {sid: s.status for sid, s in experiment.steps.items()}


def _emit_step_ready_notifications(experiment, prev_status_map):
    """Emit one ``step_ready`` notification per dependent that just unblocked.

    Compares the post-transition step statuses against ``prev_status_map``
    and fans out a single notification (to ``experiment.owner``) for each
    step that transitioned to ``READY`` since the snapshot. The
    ``add_notification`` call also writes one ``NotificationORM`` row per
    target user, so a logged-out owner still finds the notification on next
    login -- the SocketIO emit is best-effort.
    """
    owner = getattr(experiment, "owner", None)
    if not owner:
        return
    for step_id, step in experiment.steps.items():
        prev = prev_status_map.get(step_id)
        if step.status == StepStatus.READY and prev != StepStatus.READY:
            notification = notification_factories["step_ready"](
                step, experiment, target_users=[owner]
            )
            try:
                notification_service.add_notification(notification)
            except Exception as exc:
                logger.warning("step_ready notification emit failed: %s", exc)


def _emit_step_completed_notification(step, experiment):
    """Emit a single ``step_completed`` notification to the experiment's owner.

    Used for both ``complete`` and ``skip`` routes -- a skipped step is a
    completion from the dependents' perspective, so the same notification
    surfaces "this is no longer blocking downstream work".
    """
    owner = getattr(experiment, "owner", None)
    if not owner:
        return
    notification = notification_factories["step_completed"](
        step, experiment, target_users=[owner]
    )
    try:
        notification_service.add_notification(notification)
    except Exception as exc:
        logger.warning("step_completed notification emit failed: %s", exc)


def _emit_resource_conflict_notifications(experiment, conflicts):
    """Emit one ``resource_conflict`` notification per detected conflict pair.

    Called from ``update_experiment`` after the conflict scan runs. We send
    only to the experiment's owner here -- share-recipients are intentionally
    out of scope for U7 and tracked as a deferred follow-up.
    """
    owner = getattr(experiment, "owner", None)
    if not owner or not conflicts:
        return
    for conflict in conflicts:
        step_a = experiment.steps.get(conflict["step_a"])
        step_b = experiment.steps.get(conflict["step_b"])
        if step_a is None or step_b is None:
            continue
        notification = notification_factories["resource_conflict"](
            step_a, step_b, experiment, conflict["resource"], target_users=[owner]
        )
        try:
            notification_service.add_notification(notification)
        except Exception as exc:
            logger.warning("resource_conflict notification emit failed: %s", exc)


@app.route('/api/steps/<step_id>/start', methods=['POST'])
@jwt_required()
def start_step(step_id):
    step, experiment, err = _authorize_step_transition(step_id)
    if err is not None:
        return err

    scheduler.handle_step_start(step_id)
    _emit_experiment_update(experiment)
    return jsonify(experiment_to_dict(experiment))

@app.route('/api/steps/<step_id>/pause', methods=['POST'])
@jwt_required()
def pause_step(step_id):
    step, experiment, err = _authorize_step_transition(step_id)
    if err is not None:
        return err

    scheduler.handle_step_pause(step_id)
    _emit_experiment_update(experiment)
    return jsonify(experiment_to_dict(experiment))

@app.route('/api/steps/<step_id>/complete', methods=['POST'])
@jwt_required()
def complete_step(step_id):
    step, experiment, err = _authorize_step_transition(step_id)
    if err is not None:
        return err

    # Snapshot per-step status BEFORE the transition. handle_step_complete
    # runs update_ready_status internally, which can flip dependents to
    # READY -- we diff against this snapshot to fan out ``step_ready``
    # notifications for exactly the steps that just unblocked.
    prev_status_map = _snapshot_step_statuses(experiment)
    scheduler.handle_step_complete(step_id)

    # Notification fan-out (U7). The completed step gets one ``step_completed``
    # notification; each newly-READY dependent gets its own ``step_ready``.
    _emit_step_completed_notification(step, experiment)
    _emit_step_ready_notifications(experiment, prev_status_map)

    _emit_experiment_update(experiment)
    return jsonify(experiment_to_dict(experiment))


@app.route('/api/steps/<step_id>/skip', methods=['POST'])
@jwt_required()
def skip_step(step_id):
    """Mark a step as SKIPPED.

    Mirrors ``complete_step``'s shape: same auth, same permission gate, same
    return type. Differences:

    * Status transitions to ``SKIPPED`` instead of ``COMPLETED``.
    * No ``actual_end_time`` is recorded -- a skipped step never ran.
    * Newly-unblocked dependents are recomputed via ``update_ready_status``
      so a step that depended on this one becomes READY.

    Notification emits live in U7; this route only fires the
    ``experiment_update`` socket message.
    """
    step, experiment, err = _authorize_step_transition(step_id)
    if err is not None:
        return err

    # Drive the transition through the dataclass so ``elapsed_time`` /
    # ``actual_*`` stay coherent (a half-run step that gets skipped keeps the
    # work it accumulated, but no end time).
    prev_status_map = _snapshot_step_statuses(experiment)
    step.update_status(StepStatus.SKIPPED)
    # Persist the new status and recompute READY for dependents.
    scheduler._persist_step_state(step)
    scheduler.update_ready_status()
    try:
        for s in scheduler.schedule.values():
            scheduler._persist_step_state(s)
    except RuntimeError:
        # No app context (test helpers occasionally hit this); the in-memory
        # cache still reflects the change.
        pass

    # Notification fan-out (U7). Skip is treated like completion for
    # downstream-dependent purposes -- a skipped step is "done blocking"
    # whether or not it ran to completion.
    _emit_step_completed_notification(step, experiment)
    _emit_step_ready_notifications(experiment, prev_status_map)

    _emit_experiment_update(experiment)
    return jsonify(experiment_to_dict(experiment))

# Add a route to get user's experiments
@app.route('/api/user/experiments', methods=['GET'])
@jwt_required()
def get_user_experiments():
    username = get_jwt_identity()

    # Owned experiments come from the DB (no more scheduler.user_experiments).
    owned_orms = ExperimentORM.query.filter_by(owner=username).all()
    experiments = []
    seen_ids = set()
    for orm in owned_orms:
        # Pull from the cache if present (it carries any in-flight runtime
        # state); otherwise fall back to the ORM-converted dataclass.
        exp = scheduler.experiments.get(orm.id) or orm.to_dataclass()
        experiments.append(experiment_to_dict(exp))
        seen_ids.add(orm.id)

    # Shared experiments still live on the user dataclass for now (U3 will
    # normalize this into a real share table).
    user = get_user(username)
    if user:
        for exp_id in user.shared_experiments:
            if exp_id in seen_ids:
                continue
            shared = scheduler.experiments.get(exp_id)
            if shared is None:
                shared_orm = db.session.get(ExperimentORM, exp_id)
                shared = shared_orm.to_dataclass() if shared_orm else None
            if shared is not None:
                experiments.append(experiment_to_dict(shared))
                seen_ids.add(exp_id)

    return jsonify(experiments)

# Add route to share an experiment
@app.route('/api/experiments/<experiment_id>/share', methods=['POST'])
@jwt_required()
def share_experiment(experiment_id):
    username = get_jwt_identity()
    data = request.json
    share_with_username = data.get('username')
    permission = data.get('permission', 'view')  # 'view' or 'edit'
    
    # Validate input
    if not share_with_username:
        return jsonify({"error": "Username to share with is required"}), 400
    
    if permission not in ['view', 'edit']:
        return jsonify({"error": "Permission must be 'view' or 'edit'"}), 400
    
    # Get experiment
    experiment = scheduler.experiments.get(experiment_id)
    if not experiment:
        return jsonify({"error": "Experiment not found"}), 404
    
    # Check if user is the owner
    if getattr(experiment, 'owner', None) != username:
        return jsonify({"error": "Only the owner can share this experiment"}), 403
    
    # Get user to share with
    share_with_user = get_user(share_with_username)
    if not share_with_user:
        return jsonify({"error": "User to share with not found"}), 404
    
    # Share the experiment (in-memory + DB).
    experiment.shared_with[share_with_username] = permission
    share_with_user.shared_experiments[experiment_id] = permission

    # Persist the experiment's shared_with map.
    exp_orm = db.session.get(ExperimentORM, experiment_id)
    if exp_orm is not None:
        exp_orm.shared_with = dict(experiment.shared_with)
    # Persist the recipient's shared_experiments map.
    auth.persist_user(share_with_user)
    db.session.commit()

    return jsonify({"message": f"Experiment shared with {share_with_username}"}), 200

# Add export experiment endpoint
#
# Behavior change (U3): export now requires a valid JWT and view-permission on
# the experiment. The previous `optional=True` allowed unauthenticated export
# of any experiment by ID -- that's an existence-leak + data-leak vector.
# Public-share semantics are deferred to a follow-up plan; until then export
# behaves like every other read endpoint.
@app.route('/api/experiments/<experiment_id>/export', methods=['GET'])
@jwt_required()
def export_experiment(experiment_id):
    username = get_jwt_identity()
    user = get_user(username) if username else None

    experiment = scheduler.experiments.get(experiment_id)
    if not experiment or not can_view_experiment(user, experiment):
        return jsonify({"error": "Experiment not found"}), 404

    # Convert to exportable format (strip user-specific data)
    export_data = experiment_to_dict(experiment)

    # Remove owner and sharing info for privacy
    if 'owner' in export_data:
        del export_data['owner']
    if 'shared_with' in export_data:
        del export_data['shared_with']
    
    # Create a temporary file
    fd, path = tempfile.mkstemp(suffix='.json')
    try:
        with os.fdopen(fd, 'w') as tmp:
            json.dump(export_data, tmp, indent=2)
        
        # Return the file as an attachment
        return send_file(
            path,
            as_attachment=True,
            download_name=f"{experiment.name.replace(' ', '_')}_export.json",
            mimetype='application/json'
        )
    except Exception as e:
        return jsonify({"error": f"Export failed: {str(e)}"}), 500
    finally:
        # Ensure the temp file is removed after response
        try:
            os.remove(path)
        except:
            pass

# Add import experiment endpoint
@app.route('/api/experiments/import', methods=['POST'])
@jwt_required()
def import_experiment():
    username = get_jwt_identity()
    
    # Check if file was uploaded
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    if not file.filename.endswith('.json'):
        return jsonify({"error": "Only JSON files are supported"}), 400
    
    try:
        # Parse the file
        data = json.load(file)
        
        # Basic validation
        required_fields = ['name', 'steps']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Invalid experiment format: missing '{field}'"}), 400
        
        # Create a new experiment
        experiment = Experiment(
            name=data['name'],
            description=data.get('description', '')
        )
        
        # Add ownership information
        experiment.owner = username
        experiment.shared_with = {}
        
        # Add steps. Required-field check accepts the new snake_case keys
        # (``step_type`` + ``duration_seconds``); export files written by the
        # backend always emit those, so a round-trip never loses steps.
        for step_data in data.get('steps', []):
            if (
                'name' not in step_data
                or 'step_type' not in step_data
                or 'duration_seconds' not in step_data
            ):
                continue
            step = _step_from_payload(step_data)
            experiment.add_step(step)
        
        # Add to scheduler (persists to DB).
        scheduler.add_experiment(experiment)

        # Calculate initial schedule
        if experiment.steps:
            start_time = datetime.now()
            scheduler.calculate_initial_schedule(start_time=start_time)

        return jsonify(experiment_to_dict(experiment)), 201

    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON file"}), 400
    except Exception as e:
        return jsonify({"error": f"Import failed: {str(e)}"}), 500

# Add template management endpoints
@app.route('/api/templates', methods=['GET'])
@jwt_required()
def get_templates():
    username = get_jwt_identity()
    rows = TemplateORM.query.filter_by(owner=username).order_by(TemplateORM.created_at.desc()).all()
    return jsonify([r.to_dict() for r in rows])

@app.route('/api/templates', methods=['POST'])
@jwt_required()
def create_template():
    username = get_jwt_identity()
    data = request.json or {}

    if 'experiment_id' not in data or 'name' not in data:
        return jsonify({"error": "Experiment ID and template name are required"}), 400

    experiment_id = data['experiment_id']
    template_name = data['name']

    experiment = scheduler.experiments.get(experiment_id)
    if not experiment:
        return jsonify({"error": "Experiment not found"}), 404

    if getattr(experiment, 'owner', None) != username:
        return jsonify({"error": "Only the owner can create templates from this experiment"}), 403

    template = TemplateORM(
        id=str(uuid.uuid4()),
        owner=username,
        name=template_name,
        source_experiment_id=experiment_id,
        steps_payload=template_steps_payload(experiment),
    )
    db.session.add(template)
    db.session.commit()

    return jsonify(template.to_dict()), 201

@app.route('/api/templates/<template_id>', methods=['DELETE'])
@jwt_required()
def delete_template(template_id):
    username = get_jwt_identity()
    template = TemplateORM.query.filter_by(id=template_id, owner=username).first()
    if template is None:
        return jsonify({"error": "Template not found"}), 404
    db.session.delete(template)
    db.session.commit()
    return jsonify({"message": "Template deleted"}), 200

@app.route('/api/experiments/create-from-template/<template_id>', methods=['POST'])
@jwt_required()
def create_from_template(template_id):
    username = get_jwt_identity()

    template = TemplateORM.query.filter_by(id=template_id, owner=username).first()
    if template is None:
        return jsonify({"error": "Template not found"}), 404

    data = request.json or {}
    name = data.get('name', f"{template.name} - Copy")

    experiment = Experiment(
        name=name,
        description=data.get('description', '')
    )
    experiment.owner = username
    experiment.shared_with = {}

    for step_data in (template.steps_payload or []):
        # Templates store snake_case (U8). Older templates created before the
        # rename are accepted via ``_step_from_payload``'s defaults: missing
        # ``duration_seconds`` falls back to 0, missing ``step_type`` to
        # FIXED_DURATION. We don't try to translate ancient ``duration``
        # (minutes) keys here; that conversion happens once at migration time
        # if/when we ever need it.
        step = _step_from_payload(step_data)
        experiment.add_step(step)

    scheduler.add_experiment(experiment)

    if experiment.steps:
        start_time = datetime.now()
        scheduler.calculate_initial_schedule(start_time=start_time)

    return jsonify(experiment_to_dict(experiment)), 201

# Username search for the share dialog. Prefix-match by username,
# case-insensitive, capped at 25 results. Emails are intentionally NOT
# returned -- that's a privacy default; a follow-up could expose emails for
# users who already have a share/contact relationship with the requester.
@app.route('/api/users/search', methods=['GET'])
@jwt_required()
def search_users():
    q = request.args.get('q', '')
    if not q:
        return jsonify({"error": "q parameter required"}), 400

    # Case-insensitive prefix match. SQLite's LIKE is already case-insensitive
    # for ASCII; ilike makes that explicit and portable.
    rows = (
        UserORM.query
        .filter(UserORM.username.ilike(f"{q}%"))
        .order_by(UserORM.username)
        .limit(25)
        .all()
    )
    return jsonify([{"username": r.username} for r in rows])


# Add notification routes
@app.route('/api/notifications', methods=['GET'])
@jwt_required()
def get_notifications():
    username = get_jwt_identity()
    unread_only = request.args.get('unread_only', 'false').lower() == 'true'
    
    notifications = notification_service.get_user_notifications(username, unread_only)
    return jsonify([n.to_dict() for n in notifications])

@app.route('/api/notifications/<notification_id>/read', methods=['POST'])
@jwt_required()
def mark_notification_read(notification_id):
    notification_service.mark_as_read(notification_id)
    return jsonify({"message": "Notification marked as read"})

@app.route('/api/notifications/<notification_id>/dismiss', methods=['POST'])
@jwt_required()
def dismiss_notification(notification_id):
    notification_service.mark_as_dismissed(notification_id)
    return jsonify({"message": "Notification dismissed"})

@app.route('/api/notifications/<notification_id>', methods=['DELETE'])
@jwt_required()
def delete_notification(notification_id):
    success = notification_service.delete_notification(notification_id)
    if success:
        return jsonify({"message": "Notification deleted"})
    else:
        return jsonify({"error": "Notification not found"}), 404

# WebSocket event handlers for notifications
@socketio.on('connect')
def handle_connect():
    """Validate the JWT (passed via query string by socket.io clients) and join the user room."""
    try:
        verify_jwt_in_request(locations=['query_string'])
        username = get_jwt_identity()
    except Exception:
        username = None

    if username:
        join_room(f'user_{username}')
        print(f'Client connected: user_{username}')
    else:
        print('Client connected (unauthenticated)')


@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

if __name__ == "__main__":
    # Start the Flask app on port 5001 to avoid macOS AirTunes conflict on port 5000.
    # allow_unsafe_werkzeug=True is required by Flask-SocketIO 5.x in dev mode when no
    # eventlet/gevent worker is installed. Production deployments should switch to one.
    socketio.run(
        app,
        debug=True,
        port=5001,
        host='0.0.0.0',
        allow_unsafe_werkzeug=True,
    )
