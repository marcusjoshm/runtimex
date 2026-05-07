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
from scheduler import Scheduler, ScheduleConflictError
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

def _coerce_prewarning_offsets(raw) -> list:
    """Normalize pre-warning offsets from a wire payload into List[int].

    The Designer sends positive integers; we accept floats / strings too and
    coerce-or-drop. Negative / zero values are filtered out (a "pre-warning"
    at the moment of completion is meaningless; a negative offset is
    nonsense). Duplicates are de-duped while preserving order so the
    Designer's chip list and the persisted list stay aligned.
    """
    if not raw:
        return []
    seen = set()
    out = []
    for entry in raw:
        try:
            n = int(entry)
        except (TypeError, ValueError):
            continue
        if n <= 0:
            continue
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out


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
        condition_id=step_data.get('condition_id'),
        # U3 cascading time: round-trip the opt-in inherit directive. Either a
        # sibling Step's id (within the same Condition) or the literal
        # "previous". Resolution lives in start_step (below).
        inherits_elapsed_from=step_data.get('inherits_elapsed_from'),
        # U4 pre-warnings. Configuration only -- ``prewarnings_fired`` is
        # server-tracked dedup state and is never accepted from the wire (the
        # client cannot pretend it has already received a warning).
        prewarning_offsets_seconds=_coerce_prewarning_offsets(
            step_data.get('prewarning_offsets_seconds')
        ),
    )


def _condition_from_payload(experiment_id: str, condition_data, default_order: int = 0):
    """Build a Condition dataclass from the request body shape.

    Honors a client-supplied ``id`` (so existing Conditions can round-trip on
    PUT) and falls back to a fresh UUID. Defaults missing color/order_index
    to safe values.
    """
    from models import Condition  # local import; main.py already imports models
    return Condition(
        experiment_id=experiment_id,
        name=condition_data['name'],
        color=condition_data.get('color', 'slate'),
        order_index=int(condition_data.get('order_index', default_order)),
        description=condition_data.get('description'),
        id=condition_data.get('id'),
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

    # Conditions: accept from body if provided. If absent, auto-create a default
    # "Main" Condition that owns all of this experiment's Steps. Same shape the
    # backfill in db._run_migrations() produces, so legacy and fresh data look
    # identical from the route handler's perspective.
    incoming_conditions = data.get('conditions') or []
    if incoming_conditions:
        for idx, cond_data in enumerate(incoming_conditions):
            experiment.add_condition(
                _condition_from_payload(experiment.id, cond_data, default_order=idx)
            )
    else:
        experiment.ensure_default_condition()

    # Map a name-based fallback so old clients that POST steps without
    # condition_id can still work: they all land in the default "Main"
    # Condition. Only used if the client also didn't send a conditions array.
    default_condition_id = next(iter(experiment.conditions.values())).id

    for step_data in data.get('steps', []):
        step = _step_from_payload(step_data)
        # Honor client-supplied step id so dependencies resolve correctly.
        # Without this, dependencies: ["step1"] would never match because the
        # dataclass mints a fresh UUID and "step1" doesn't exist on the
        # experiment.
        if step_data.get('id'):
            step.id = step_data['id']
        if not step.condition_id:
            step.condition_id = default_condition_id
        if step.condition_id not in experiment.conditions:
            return jsonify({
                'error': f"Step references unknown condition_id '{step.condition_id}'"
            }), 400
        experiment.add_step(step)

    try:
        scheduler.add_experiment(experiment)
    except ScheduleConflictError as exc:
        # Cross-condition dependency rejected by _sync_step_dependencies.
        return jsonify({'error': str(exc)}), 400

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

    # Conditions: when present, reconcile by ID. New conditions are added,
    # existing ones get name/color/order_index/description updates, missing
    # ones are removed (cascading removes steps assigned to them at the DB
    # layer thanks to the upsert path that follows).
    if 'conditions' in data:
        incoming_conds = data['conditions'] or []
        incoming_ids = {c.get('id') for c in incoming_conds if c.get('id')}
        # Remove orphan Conditions not present in the incoming list.
        for old_id in list(experiment.conditions.keys()):
            if old_id not in incoming_ids:
                experiment.conditions.pop(old_id, None)
        # Apply edits + adds.
        for idx, cond_data in enumerate(incoming_conds):
            cond_id = cond_data.get('id')
            if cond_id and cond_id in experiment.conditions:
                target = experiment.conditions[cond_id]
                target.name = cond_data.get('name', target.name)
                target.color = cond_data.get('color', target.color)
                target.order_index = int(cond_data.get('order_index', idx))
                target.description = cond_data.get('description', target.description)
            else:
                experiment.add_condition(
                    _condition_from_payload(experiment.id, cond_data, default_order=idx)
                )

    # Always ensure at least one Condition exists -- otherwise step.condition_id
    # has no valid target. The default "Main" matches the backfill shape.
    if not experiment.conditions:
        experiment.ensure_default_condition()

    if 'steps' in data:
        default_condition_id = next(iter(experiment.conditions.values())).id

        # Build a list of incoming Step objects. If the client sends an `id`
        # we honor it (used by existing-step edits); otherwise we mint a new
        # one (treated as a brand-new step).
        incoming = []
        for step_data in data['steps']:
            new_step = _step_from_payload(step_data)
            if step_data.get('id'):
                new_step.id = step_data['id']
            if not new_step.condition_id:
                new_step.condition_id = default_condition_id
            if new_step.condition_id not in experiment.conditions:
                return jsonify({
                    'error': f"Step references unknown condition_id '{new_step.condition_id}'"
                }), 400
            incoming.append(new_step)

        try:
            scheduler.upsert_experiment_steps(experiment, incoming)
        except ScheduleConflictError as exc:
            return jsonify({'error': str(exc)}), 400

        # Recalculate schedule for any newly-added (PENDING) steps. Existing
        # RUNNING/COMPLETED steps are skipped by calculate_initial_schedule.
        start_time = datetime.now()
        scheduler.calculate_initial_schedule(start_time=start_time)
    else:
        # Conditions changed but steps didn't -- still need to persist the
        # condition mutations. Re-write the experiment row to flush them.
        scheduler._persist_experiment(experiment)

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


def _resolve_inherits_elapsed(step, experiment):
    """U3: resolve ``step.inherits_elapsed_from`` to a source Step's elapsed.

    Called from ``start_step`` BEFORE ``Step.start()`` runs, so the seed
    survives the dataclass's own ``elapsed_time`` reset semantics: ``start()``
    from READY leaves elapsed_time alone (it's already 0 by construction), so
    pre-populating the dataclass here is enough to flow through to the ORM
    via ``_persist_step_state``.

    Resolution rules:
      * ``"previous"`` -> the immediately preceding Step in the SAME Condition
        ordered by ``created_at`` (the canonical order_by on ``StepORM.steps``
        and ``ConditionORM.steps``). Falls back to dict insertion order on the
        dataclass since it mirrors ``ConditionORM.steps``'s order_by.
      * Any other string -> treated as a Step id; must be in the SAME
        Condition.

    The seed only fires when the source step has ``actual_end_time`` set
    (i.e. has COMPLETED). Otherwise we log a warning and proceed with
    ``elapsed_time = 0``. Cross-Condition references log a warning and skip.
    First-step-in-Condition case (``"previous"`` with no preceding sibling)
    silently treats as no-inherit -- ``elapsed_time = 0`` is the natural
    "nothing to inherit" outcome.

    Pure side-effect on ``step.elapsed_time``; returns nothing.
    """
    directive = getattr(step, "inherits_elapsed_from", None)
    if not directive:
        return
    if step.status != StepStatus.READY:
        # Resume-from-PAUSED already has accumulated elapsed_time; don't clobber it.
        return

    source = None
    if directive == "previous":
        # Order siblings by created_at via the ORM (the dataclass cache loses
        # that detail). Fall back to insertion order if we can't reach the ORM
        # (e.g., bare-Scheduler test harnesses without app context).
        siblings = [
            s for s in experiment.steps.values()
            if getattr(s, "condition_id", None) == step.condition_id
        ]
        try:
            from models import StepORM as _StepORM
            ordered_ids = [
                row.id for row in (
                    db.session.query(_StepORM)
                    .filter(_StepORM.experiment_id == experiment.id)
                    .filter(_StepORM.condition_id == step.condition_id)
                    .order_by(_StepORM.created_at)
                    .all()
                )
            ]
            if ordered_ids:
                # Reorder dataclass siblings to match created_at order. Steps
                # not present in ordered_ids (mid-add edge cases) drop out.
                by_id = {s.id: s for s in siblings}
                siblings = [by_id[sid] for sid in ordered_ids if sid in by_id]
        except RuntimeError:
            pass

        # Find the immediate predecessor.
        predecessor = None
        for s in siblings:
            if s.id == step.id:
                break
            predecessor = s
        if predecessor is None:
            logger.warning(
                "inherits_elapsed_from='previous' on step '%s' has no preceding "
                "sibling in condition %s; proceeding with elapsed=0",
                step.name, step.condition_id,
            )
            return
        source = predecessor
    else:
        source = experiment.steps.get(directive)
        if source is None:
            logger.warning(
                "inherits_elapsed_from='%s' on step '%s' references unknown "
                "step id; proceeding with elapsed=0",
                directive, step.name,
            )
            return
        if getattr(source, "condition_id", None) != step.condition_id:
            logger.warning(
                "inherits_elapsed_from='%s' on step '%s' references a step in "
                "a different Condition (%s vs %s); proceeding with elapsed=0",
                directive, step.name, source.condition_id, step.condition_id,
            )
            return

    # Source must have COMPLETED for the seed to be meaningful. A still-RUNNING
    # source has no final elapsed yet -- skip with a warning rather than seed
    # from a partial value (which would silently double-count when the source
    # eventually finishes).
    if source.actual_end_time is None:
        logger.warning(
            "inherits_elapsed_from on step '%s' references step '%s' which has "
            "not completed yet; proceeding with elapsed=0",
            step.name, source.name,
        )
        return

    step.elapsed_time = source.elapsed_time
    logger.info(
        "Step '%s' inheriting elapsed=%ss from '%s'",
        step.name, step.elapsed_time.total_seconds(), source.name,
    )


@app.route('/api/steps/<step_id>/start', methods=['POST'])
@jwt_required()
def start_step(step_id):
    step, experiment, err = _authorize_step_transition(step_id)
    if err is not None:
        return err

    # U3: pre-seed elapsed_time from a sibling before Step.start() flips status.
    # The seed must happen before scheduler.handle_step_start() so the
    # _persist_step_state call inside picks up the new elapsed_seconds value.
    _resolve_inherits_elapsed(step, experiment)

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

# ---------------------------------------------------------------------------
# U5 reactive live-edit routes.
#
# Two narrow operations the Runner / Designer use to react when reality drifts:
#
#   * POST /api/steps/<id>/extend  -- "+5m / -5m" on the active step.
#   * POST /api/conditions/<id>/push -- "shift this whole Condition by N min".
#
# Both follow the same shape as existing step-state routes: JWT-gated,
# permission-gated, persist via the scheduler, run conflict detection, emit
# ``experiment_update``, return ``{experiment, conflicts}``.
# ---------------------------------------------------------------------------
def _coerce_delta_seconds(payload):
    """Pull a signed integer ``delta_seconds`` out of a JSON body.

    Accepts numeric strings ("300", "-60") for client-side flexibility; rejects
    anything non-numeric. Returns ``(delta, error_response)`` so callers can
    surface a 400 directly without re-implementing the same try/except.
    """
    if not isinstance(payload, dict):
        return None, (jsonify({'error': 'JSON body required'}), 400)
    raw = payload.get('delta_seconds')
    if raw is None:
        return None, (jsonify({'error': 'delta_seconds is required'}), 400)
    try:
        return int(raw), None
    except (TypeError, ValueError):
        return None, (jsonify({'error': 'delta_seconds must be an integer'}), 400)


@app.route('/api/steps/<step_id>/extend', methods=['POST'])
@jwt_required()
def extend_step(step_id):
    """Reactive extend/shrink on the active (or any future) step.

    Wire contract:
      Request:  ``{"delta_seconds": <int>}`` -- positive extends, negative
                shrinks. Zero is treated as a no-op (still returns 200 with
                the current experiment payload so clients can retry idempotently).
      Response: ``{...experiment_to_dict..., "conflicts": [...], "warning"?: str}``

    Permission policy mirrors other step-state routes via
    ``_authorize_step_transition``: 404 when the user can't view the parent
    experiment (existence-privacy), 403 when they can view but not edit.

    Shrink-clamp semantics: a negative delta that would push duration below
    the step's current ``elapsed_seconds`` clamps to ``elapsed_seconds + 1``
    and surfaces a ``warning`` field in the response. Plan's contract.
    """
    step, experiment, err = _authorize_step_transition(step_id)
    if err is not None:
        return err

    delta, err = _coerce_delta_seconds(request.json or {})
    if err is not None:
        return err

    changed, warning = scheduler.extend_step_duration(step, delta)
    if changed:
        # Re-derive scheduled times for downstream PENDING/READY siblings. The
        # current step's own scheduled_end_time was already updated inline in
        # extend_step_duration; calculate_initial_schedule only touches PENDING
        # steps, so RUNNING/COMPLETED siblings stay put.
        scheduler.calculate_initial_schedule(start_time=datetime.now())
        _emit_experiment_update(experiment)

    conflicts = Scheduler.check_for_conflicts(experiment)
    payload = experiment_to_dict(experiment)
    payload["conflicts"] = conflicts
    if warning:
        payload["warning"] = warning
    return jsonify(payload)


@app.route('/api/conditions/<condition_id>/push', methods=['POST'])
@jwt_required()
def push_condition(condition_id):
    """Shift PENDING/READY steps in a Condition by ``delta_seconds``.

    Wire contract:
      Request:  ``{"delta_seconds": <int>}``
      Response: ``{...experiment_to_dict..., "conflicts": [...]}``

    Permission policy: existence-privacy on the parent experiment. We resolve
    the condition's parent by walking ``scheduler.experiments`` (same pattern
    as ``_find_experiment_for_step``), so a foreign condition_id and a
    non-existent condition_id are indistinguishable from the caller's view --
    both produce 404.

    ``delta_seconds == 0`` is a documented no-op: no DB write, no socket emit,
    just the current experiment payload. Clients sending zero (e.g. a
    debounced UI control that snapped to zero) shouldn't see phantom traffic.
    """
    delta, err = _coerce_delta_seconds(request.json or {})
    if err is not None:
        return err

    username = get_jwt_identity()
    user = get_user(username) if username else None

    # Resolve the parent experiment by walking the cache. We don't expose
    # condition existence to unauthorized callers -- the 404 path covers both
    # "no such condition" and "condition belongs to an experiment you can't
    # view".
    experiment = None
    for exp in scheduler.experiments.values():
        if condition_id in (exp.conditions or {}):
            experiment = exp
            break

    if experiment is None or not can_view_experiment(user, experiment):
        return jsonify({'error': 'Condition not found'}), 404
    if not can_edit_experiment(user, experiment):
        return jsonify({'error': 'edit permission required'}), 403

    if delta == 0:
        # No-op path: skip DB write + socket emit but still return the
        # experiment payload + conflicts so clients can use the response
        # uniformly with the non-zero path.
        conflicts = Scheduler.check_for_conflicts(experiment)
        payload = experiment_to_dict(experiment)
        payload["conflicts"] = conflicts
        return jsonify(payload)

    moved = scheduler.push_condition(experiment, condition_id, delta)
    if moved:
        _emit_experiment_update(experiment)

    conflicts = Scheduler.check_for_conflicts(experiment)
    payload = experiment_to_dict(experiment)
    payload["conflicts"] = conflicts
    return jsonify(payload)


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


@socketio.on('prewarning_hit')
def handle_prewarning_hit(payload):
    """Server-side dedupe for U4 pre-warnings.

    Contract: clients tick once per second and emit ``prewarning_hit`` with
    ``{step_id, offset_seconds}`` whenever ``(expected_end - now) <= offset``
    AND the offset isn't yet in ``prewarnings_fired``. The server is the
    source of truth for "did we already fire this offset?" -- on receipt:

      * Validate the JWT (same query-string transport as ``connect``).
      * Resolve the step + experiment. Silent no-op (NOT 401) if the user
        can't view the experiment -- consistent with existing connect-handler
        behaviour. We don't want this socket event to be a probe vector for
        existence-privacy.
      * Validate ``offset_seconds`` is in ``step.prewarning_offsets_seconds``
        AND NOT already in ``step.prewarnings_fired``.
      * On valid+fresh: append to ``prewarnings_fired``, persist via
        ``scheduler._persist_step_state``, fire the notification factory,
        emit experiment_update so other tabs see the updated fired list.
      * On duplicate: silent no-op.

    Limitation accepted in v1: pre-warnings only fire when at least one user
    client has the Runner open. Background-tick delivery is the deferred
    follow-up. See plan §"Pre-warning delivery" for the rationale.
    """
    try:
        verify_jwt_in_request(locations=['query_string'])
        username = get_jwt_identity()
    except Exception:
        # Unauthenticated client -- silently drop. We deliberately don't emit
        # an error event back; clients can't recover from missing auth here
        # and a leaked error type would help an attacker probe.
        return

    if not isinstance(payload, dict):
        return
    step_id = payload.get('step_id')
    raw_offset = payload.get('offset_seconds')
    if not step_id or raw_offset is None:
        return
    try:
        offset_seconds = int(raw_offset)
    except (TypeError, ValueError):
        return

    user = get_user(username) if username else None
    step = scheduler.get_step(step_id)
    experiment = _find_experiment_for_step(step_id) if step else None
    if not step or not experiment:
        return
    # Existence-privacy: a user without view permission learns nothing here.
    # No 401 / no error event -- just return silently.
    if not can_view_experiment(user, experiment):
        return

    # Validate the offset is one the step actually declared. Defensive: don't
    # let a malicious client pollute prewarnings_fired with arbitrary numbers.
    declared = list(step.prewarning_offsets_seconds or [])
    if offset_seconds not in declared:
        return

    fired = list(step.prewarnings_fired or [])
    if offset_seconds in fired:
        # Duplicate fire -- the dedupe contract holds. The second emitter
        # gets a silent no-op; their UI will see the post-fire experiment
        # snapshot via the broadcast we already sent on the first emit.
        return

    # Fresh fire. Append + persist before broadcasting so any client that
    # immediately re-fetches sees the updated state.
    fired.append(offset_seconds)
    step.prewarnings_fired = fired
    try:
        scheduler._persist_step_state(step)
    except Exception as exc:
        logger.warning("prewarning_hit persist failed: %s", exc)
        # Don't fan out the notification on persist failure -- the dedupe
        # state didn't actually save, so a retry should still fire it.
        return

    owner = getattr(experiment, "owner", None)
    if owner:
        try:
            notification = notification_factories["step_prewarning"](
                step, experiment, offset_seconds, target_users=[owner]
            )
            notification_service.add_notification(notification)
        except Exception as exc:
            logger.warning("step_prewarning notification emit failed: %s", exc)

    # Push the updated experiment so every connected client (including other
    # tabs of the same user) refreshes their local prewarnings_fired list and
    # stops emitting for this offset.
    _emit_experiment_update(experiment)

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
