"""Wire-format serializers for runtimex.

Centralizes the dataclass-to-dict conversions that produce the JSON the
frontend consumes. Every field on the wire is **snake_case** (U8); the
ORM/dataclass field names already match in most cases, so the bulk of this
module is plain attribute access.

Two notable shape decisions:

* ``duration_seconds`` is emitted as a float (``timedelta.total_seconds()``).
  The pre-U8 inline serializer floor-divided by 60 to "convert to minutes",
  which truncated any sub-minute step to zero (the audit's ``// 60`` bug).
  The frontend converts seconds -> "X min" / "<1 min" for display.
* ``elapsed_seconds`` (NOT ``elapsedTime`` or ``elapsed_time``) mirrors the
  ORM column name. The frontend Runner derives a per-tick elapsed value from
  ``actual_start_time`` for sub-second responsiveness; this server-snapshot
  field is used for resumed-from-pause math and history display.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def step_to_dict(step) -> Dict[str, Any]:
    """Serialize a single ``Step`` dataclass to its on-the-wire dict shape.

    All keys are snake_case. Optional time fields are only included when the
    underlying value is not ``None`` so the frontend can distinguish "never
    happened" from "happened at epoch zero" without a sentinel.
    """
    out: Dict[str, Any] = {
        "id": step.id,
        "name": step.name,
        "step_type": step.step_type.value,
        # ``duration_seconds`` is a float -- the source of truth is
        # ``timedelta.total_seconds()``. See module docstring for why we
        # don't floor-divide by 60 here.
        "duration_seconds": step.duration.total_seconds() if step.duration else 0.0,
        "status": step.status.value,
        "dependencies": list(step.dependencies or []),
        "notes": step.notes,
        # ``resource_required`` aligns the wire-name with the ORM column
        # (``resource_needed`` -- see backend/models.py:357). The dataclass
        # attribute is named ``resource_needed`` for legacy reasons; the wire
        # name is what U8 normalizes.
        "resource_required": step.resource_needed,
    }

    if step.scheduled_start_time:
        out["scheduled_start_time"] = step.scheduled_start_time.isoformat()
    if step.scheduled_end_time:
        out["scheduled_end_time"] = step.scheduled_end_time.isoformat()
    if step.actual_start_time:
        out["actual_start_time"] = step.actual_start_time.isoformat()
    # ``first_start_time`` is set on the very first start() and preserved
    # across pause/resume cycles; the Runner reads it for "when did this
    # step originally begin?" displays.
    first_start_time = getattr(step, "first_start_time", None)
    if first_start_time:
        out["first_start_time"] = first_start_time.isoformat()
    if step.actual_end_time:
        out["actual_end_time"] = step.actual_end_time.isoformat()
    if step.elapsed_time:
        out["elapsed_seconds"] = step.elapsed_time.total_seconds()

    return out


def experiment_to_dict(experiment) -> Dict[str, Any]:
    """Serialize an ``Experiment`` dataclass to its on-the-wire dict shape.

    The ``conflicts`` field is NOT attached here -- callers (specifically
    ``update_experiment``) layer it on after running ``check_for_conflicts``
    so the conflict list is available alongside the experiment without
    requiring this helper to know about the scheduler.
    """
    steps: List[Dict[str, Any]] = [
        step_to_dict(step) for _step_id, step in experiment.steps.items()
    ]

    result: Dict[str, Any] = {
        "id": experiment.id,
        "name": experiment.name,
        "description": experiment.description,
        "steps": steps,
    }

    # Ownership / sharing metadata is attached to the dataclass at request
    # time by the route handlers, so it isn't always present on freshly-built
    # ``Experiment`` instances. Serialize it only if set.
    if hasattr(experiment, "owner"):
        result["owner"] = experiment.owner
    if hasattr(experiment, "shared_with"):
        result["shared_with"] = dict(experiment.shared_with or {})

    return result


def template_steps_payload(experiment) -> List[Dict[str, Any]]:
    """Build the ``steps_payload`` list stored in a ``TemplateORM`` row.

    Templates store a denormalized snapshot of their source experiment's
    steps so they survive the source being edited or deleted. Same wire
    format as ``step_to_dict`` minus the runtime-only fields (status,
    actual_*, elapsed) -- a template is a pre-execution shape.
    """
    payload: List[Dict[str, Any]] = []
    for _step_id, step in experiment.steps.items():
        payload.append(
            {
                "name": step.name,
                "step_type": step.step_type.value,
                "duration_seconds": step.duration.total_seconds() if step.duration else 0.0,
                "dependencies": list(step.dependencies or []),
                "notes": step.notes,
                "resource_required": step.resource_needed,
            }
        )
    return payload


def notification_to_dict(notification) -> Dict[str, Any]:
    """Serialize a ``Notification`` to its on-the-wire dict shape.

    Notifications were already snake_case prior to U8 (see
    ``Notification.to_dict`` in ``notifications.py``); this wrapper just
    delegates so all wire serializers live in one module. Importers should
    prefer this entry point.
    """
    return notification.to_dict()
