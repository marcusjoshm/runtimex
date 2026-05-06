"""Permission helpers for experiment + step access control.

These helpers operate against the dataclass shapes that the route handlers
already pass around (``User``, ``Experiment``, ``Step``). Each helper returns
a bool; callers translate that into the appropriate HTTP status.

Status-code policy (enforced by callers, documented here for reference):

* No view permission        -> 404 (preserve existence privacy).
* View but not edit         -> 403.
* JWT missing / expired     -> 401 (handled upstream by ``@jwt_required``).
"""

from typing import Optional


def _shared_permission(experiment, username: str) -> Optional[str]:
    """Return the share permission for ``username`` on ``experiment``, or None."""
    shared_with = getattr(experiment, "shared_with", None) or {}
    return shared_with.get(username)


def can_view_experiment(user, experiment) -> bool:
    """True if the user owns the experiment or has any share on it."""
    if user is None or experiment is None:
        return False
    username = getattr(user, "username", None) or user
    if getattr(experiment, "owner", None) == username:
        return True
    return _shared_permission(experiment, username) is not None


def can_edit_experiment(user, experiment) -> bool:
    """True if the user owns the experiment or has an ``edit`` share."""
    if user is None or experiment is None:
        return False
    username = getattr(user, "username", None) or user
    if getattr(experiment, "owner", None) == username:
        return True
    return _shared_permission(experiment, username) == "edit"


def can_run_step(user, step, experiment) -> bool:
    """True if the user can transition ``step`` state.

    Currently identical to ``can_edit_experiment`` on the parent experiment;
    the ``step`` argument is accepted for forward compatibility with finer
    grained per-step permissions.
    """
    return can_edit_experiment(user, experiment)
