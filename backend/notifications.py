from enum import Enum
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
import json

from db import db

# Define notification types
class NotificationType(Enum):
    STEP_READY = "step_ready"
    STEP_COMPLETED = "step_completed"
    STEP_PAUSED = "step_paused"
    STEP_TIMEOUT = "step_timeout"
    STEP_PREWARNING = "step_prewarning"
    RESOURCE_CONFLICT = "resource_conflict"
    USER_ATTENTION_REQUIRED = "user_attention_required"
    GENERAL_INFO = "general_info"
    ERROR = "error"
    CUSTOM = "custom"

# Define notification priority
class NotificationPriority(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

# Define delivery methods
class DeliveryMethod(Enum):
    IN_APP = "in_app"
    EMAIL = "email"
    PUSH = "push"
    SMS = "sms"  # For future implementation

# Define notification action types
class ActionType(Enum):
    LINK = "link"  # Navigate to a URL
    BUTTON = "button"  # Trigger a callback
    FORM = "form"  # Show a form for user input
    DISMISS = "dismiss"  # Just dismiss the notification
    SNOOZE = "snooze"  # Dismiss and remind later

# Notification action class
class NotificationAction:
    def __init__(self, 
                 action_id: str, 
                 action_type: ActionType, 
                 label: str,
                 data: Optional[Dict[str, Any]] = None):
        self.id = action_id
        self.type = action_type
        self.label = label
        self.data = data or {}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "label": self.label,
            "data": self.data
        }

# Main notification class
class Notification:
    def __init__(self,
                 title: str,
                 message: str,
                 notification_type: NotificationType,
                 priority: NotificationPriority = NotificationPriority.MEDIUM,
                 target_users: Optional[List[str]] = None,
                 experiment_id: Optional[str] = None,
                 step_id: Optional[str] = None,
                 metadata: Optional[Dict[str, Any]] = None,
                 actions: Optional[List[NotificationAction]] = None,
                 delivery_methods: Optional[List[DeliveryMethod]] = None):
        self.id = str(uuid.uuid4())
        self.title = title
        self.message = message
        self.type = notification_type
        self.priority = priority
        self.target_users = target_users or []
        self.experiment_id = experiment_id
        self.step_id = step_id
        self.metadata = metadata or {}
        self.actions = actions or []
        self.delivery_methods = delivery_methods or [DeliveryMethod.IN_APP]
        self.created_at = datetime.now()
        self.is_read = False
        self.is_dismissed = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "message": self.message,
            "type": self.type.value,
            "priority": self.priority.value,
            "target_users": self.target_users,
            "experiment_id": self.experiment_id,
            "step_id": self.step_id,
            "metadata": self.metadata,
            "actions": [action.to_dict() for action in self.actions],
            "delivery_methods": [method.value for method in self.delivery_methods],
            "created_at": self.created_at.isoformat(),
            "is_read": self.is_read,
            "is_dismissed": self.is_dismissed
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Notification':
        notification = cls(
            title=data["title"],
            message=data["message"],
            notification_type=NotificationType(data["type"]),
            priority=NotificationPriority(data["priority"]),
            target_users=data.get("target_users", []),
            experiment_id=data.get("experiment_id"),
            step_id=data.get("step_id"),
            metadata=data.get("metadata", {}),
            delivery_methods=[DeliveryMethod(m) for m in data.get("delivery_methods", ["in_app"])]
        )
        
        # Set other properties
        notification.id = data["id"]
        notification.created_at = datetime.fromisoformat(data["created_at"])
        notification.is_read = data.get("is_read", False)
        notification.is_dismissed = data.get("is_dismissed", False)
        
        # Add actions
        for action_data in data.get("actions", []):
            action = NotificationAction(
                action_id=action_data["id"],
                action_type=ActionType(action_data["type"]),
                label=action_data["label"],
                data=action_data.get("data", {})
            )
            notification.actions.append(action)
        
        return notification

# Notification service
class NotificationService:
    """Notification storage + delivery, backed by NotificationORM.

    The legacy ``create_notification`` method name is kept for compatibility
    with `main.py`. Internally it delegates to ``add_notification``.
    """

    def __init__(self, socketio=None):
        self.socketio = socketio

        # Register notification handlers for different step types
        self.notification_handlers = {
            NotificationType.STEP_READY: self._handle_step_ready,
            NotificationType.STEP_COMPLETED: self._handle_step_completed,
            NotificationType.STEP_PAUSED: self._handle_step_paused,
            NotificationType.STEP_TIMEOUT: self._handle_step_timeout,
            NotificationType.RESOURCE_CONFLICT: self._handle_resource_conflict,
            NotificationType.USER_ATTENTION_REQUIRED: self._handle_user_attention_required,
            NotificationType.ERROR: self._handle_error,
            # GENERAL_INFO and CUSTOM don't need special handling
        }

    # ------------------------------------------------------------------
    # ORM <-> Notification conversion
    # ------------------------------------------------------------------
    @staticmethod
    def _orm_to_notification(orm) -> 'Notification':
        n = Notification(
            title=orm.title,
            message=orm.message,
            notification_type=NotificationType(orm.type),
            priority=NotificationPriority(orm.priority),
            target_users=[orm.target_user],
            experiment_id=orm.experiment_id,
            step_id=orm.step_id,
            metadata=dict(orm.notification_metadata or {}),
            delivery_methods=[DeliveryMethod(m) for m in (orm.delivery_methods or ['in_app'])],
        )
        n.id = orm.id
        n.created_at = orm.created_at
        n.is_read = orm.is_read
        n.is_dismissed = orm.is_dismissed
        for action_data in (orm.actions or []):
            n.actions.append(NotificationAction(
                action_id=action_data['id'],
                action_type=ActionType(action_data['type']),
                label=action_data['label'],
                data=action_data.get('data', {}),
            ))
        return n

    @staticmethod
    def _notification_to_orm_rows(notification: 'Notification') -> List:
        """Build one NotificationORM row per target_user.

        We fan out per-user so the ``target_user`` column can be a simple
        FK + index. The notification id is shared across rows so callers can
        still treat it as "the" notification id; mark/dismiss/delete update
        every row with that id.
        """
        from models import NotificationORM
        rows = []
        for user in notification.target_users:
            rows.append(NotificationORM(
                id=notification.id,
                target_user=user,
                title=notification.title,
                message=notification.message,
                type=notification.type.value,
                priority=notification.priority.value,
                experiment_id=notification.experiment_id,
                step_id=notification.step_id,
                notification_metadata=dict(notification.metadata or {}),
                actions=[a.to_dict() for a in notification.actions],
                delivery_methods=[m.value for m in notification.delivery_methods],
                created_at=notification.created_at,
                is_read=notification.is_read,
                is_dismissed=notification.is_dismissed,
            ))
        return rows

    # ------------------------------------------------------------------
    # Public API (back-compat names preserved)
    # ------------------------------------------------------------------
    def add_notification(self, notification: Notification) -> str:
        """Persist a notification + emit on socket. Replaces old in-memory dict."""
        from models import NotificationORM

        # Run type-specific handler first (may mutate notification.actions etc.)
        if notification.type in self.notification_handlers:
            self.notification_handlers[notification.type](notification)

        rows = self._notification_to_orm_rows(notification)
        for row in rows:
            db.session.add(row)
        db.session.commit()

        if self.socketio:
            for user in notification.target_users:
                self.socketio.emit(
                    'notification',
                    notification.to_dict(),
                    room=f'user_{user}'
                )

        return notification.id

    # Legacy alias used by main.py and the notification factories.
    def create_notification(self, notification: Notification) -> str:
        return self.add_notification(notification)

    def get_user_notifications(self, username: str, unread_only: bool = False) -> List[Notification]:
        """Get all notifications for a user, newest first."""
        from models import NotificationORM

        q = NotificationORM.query.filter_by(target_user=username)
        if unread_only:
            q = q.filter_by(is_read=False)
        rows = q.order_by(NotificationORM.created_at.desc()).all()
        return [self._orm_to_notification(r) for r in rows]

    def mark_as_read(self, notification_id: str) -> bool:
        from models import NotificationORM

        rows = NotificationORM.query.filter_by(id=notification_id).all()
        if not rows:
            return False
        for r in rows:
            r.is_read = True
        db.session.commit()
        return True

    def mark_as_dismissed(self, notification_id: str) -> bool:
        from models import NotificationORM

        rows = NotificationORM.query.filter_by(id=notification_id).all()
        if not rows:
            return False
        for r in rows:
            r.is_dismissed = True
        db.session.commit()
        return True

    def delete_notification(self, notification_id: str) -> bool:
        from models import NotificationORM

        rows = NotificationORM.query.filter_by(id=notification_id).all()
        if not rows:
            return False
        for r in rows:
            db.session.delete(r)
        db.session.commit()
        return True
    
    # --- Notification Type Handlers ---
    
    def _handle_step_ready(self, notification: Notification):
        """Handle STEP_READY notifications"""
        # Add start action
        if notification.step_id:
            notification.actions.append(
                NotificationAction(
                    action_id="start_step",
                    action_type=ActionType.BUTTON,
                    label="Start Step",
                    data={"step_id": notification.step_id}
                )
            )
    
    def _handle_step_completed(self, notification: Notification):
        """Handle STEP_COMPLETED notifications"""
        # No special handling needed
        pass
    
    def _handle_step_paused(self, notification: Notification):
        """Handle STEP_PAUSED notifications"""
        if notification.step_id:
            notification.actions.append(
                NotificationAction(
                    action_id="resume_step",
                    action_type=ActionType.BUTTON,
                    label="Resume Step",
                    data={"step_id": notification.step_id}
                )
            )
    
    def _handle_step_timeout(self, notification: Notification):
        """Handle STEP_TIMEOUT notifications"""
        if notification.step_id:
            notification.actions.append(
                NotificationAction(
                    action_id="complete_step",
                    action_type=ActionType.BUTTON,
                    label="Mark as Complete",
                    data={"step_id": notification.step_id}
                )
            )
    
    def _handle_resource_conflict(self, notification: Notification):
        """Handle RESOURCE_CONFLICT notifications"""
        # Add actions for conflict resolution
        if notification.step_id and notification.metadata.get("conflicting_step_id"):
            notification.actions.extend([
                NotificationAction(
                    action_id="pause_step",
                    action_type=ActionType.BUTTON,
                    label="Pause Current Step",
                    data={"step_id": notification.step_id}
                ),
                NotificationAction(
                    action_id="pause_conflicting_step",
                    action_type=ActionType.BUTTON,
                    label="Pause Conflicting Step",
                    data={"step_id": notification.metadata["conflicting_step_id"]}
                )
            ])
    
    def _handle_user_attention_required(self, notification: Notification):
        """Handle USER_ATTENTION_REQUIRED notifications"""
        if notification.step_id:
            notification.actions.append(
                NotificationAction(
                    action_id="view_step",
                    action_type=ActionType.LINK,
                    label="View Step",
                    data={"link": f"/run/{notification.experiment_id}?focus={notification.step_id}"}
                )
            )
    
    def _handle_error(self, notification: Notification):
        """Handle ERROR notifications"""
        # Set priority to high for errors
        notification.priority = NotificationPriority.HIGH

# Helper function to create notification factories for common scenarios
def create_notification_factories(scheduler):
    """Create notification factory functions for common scenarios"""
    
    def step_ready_notification(step, experiment, target_users=None):
        """Create a notification when a step is ready to start"""
        return Notification(
            title=f"Step Ready: {step.name}",
            message=f"The step '{step.name}' in experiment '{experiment.name}' is ready to start.",
            notification_type=NotificationType.STEP_READY,
            priority=NotificationPriority.MEDIUM,
            target_users=target_users or ([experiment.owner] if hasattr(experiment, 'owner') else []),
            experiment_id=experiment.id,
            step_id=step.id,
            metadata={
                "scheduled_start_time": step.scheduled_start_time.isoformat() if step.scheduled_start_time else None,
                "step_type": step.step_type.value
            }
        )
    
    def step_completed_notification(step, experiment, target_users=None):
        """Create a notification when a step is completed"""
        return Notification(
            title=f"Step Completed: {step.name}",
            message=f"The step '{step.name}' in experiment '{experiment.name}' has been completed.",
            notification_type=NotificationType.STEP_COMPLETED,
            priority=NotificationPriority.LOW,
            target_users=target_users or ([experiment.owner] if hasattr(experiment, 'owner') else []),
            experiment_id=experiment.id,
            step_id=step.id
        )
    
    def resource_conflict_notification(step1, step2, experiment, resource, target_users=None):
        """Create a notification for resource conflicts"""
        return Notification(
            title=f"Resource Conflict: {resource}",
            message=f"Resource conflict detected: '{step1.name}' and '{step2.name}' both need '{resource}'.",
            notification_type=NotificationType.RESOURCE_CONFLICT,
            priority=NotificationPriority.HIGH,
            target_users=target_users or ([experiment.owner] if hasattr(experiment, 'owner') else []),
            experiment_id=experiment.id,
            step_id=step1.id,
            metadata={
                "resource": resource,
                "conflicting_step_id": step2.id,
                "conflicting_step_name": step2.name
            }
        )
    
    def user_attention_notification(step, experiment, target_users=None):
        """Create a notification when user attention is required"""
        return Notification(
            title=f"Attention Required: {step.name}",
            message=f"Your attention is required for step '{step.name}' in experiment '{experiment.name}'.",
            notification_type=NotificationType.USER_ATTENTION_REQUIRED,
            priority=NotificationPriority.HIGH,
            target_users=target_users or ([experiment.owner] if hasattr(experiment, 'owner') else []),
            experiment_id=experiment.id,
            step_id=step.id
        )
    
    def step_timeout_notification(step, experiment, target_users=None):
        """Create a notification when a step times out"""
        return Notification(
            title=f"Step Timeout: {step.name}",
            message=f"The step '{step.name}' in experiment '{experiment.name}' has exceeded its expected duration.",
            notification_type=NotificationType.STEP_TIMEOUT,
            priority=NotificationPriority.MEDIUM,
            target_users=target_users or ([experiment.owner] if hasattr(experiment, 'owner') else []),
            experiment_id=experiment.id,
            step_id=step.id
        )

    def step_prewarning_notification(step, experiment, offset_seconds, target_users=None):
        """Create a pre-warning notification for a step nearing its end (U4).

        Mirrors the shape of ``step_timeout_notification``: same target-user
        defaulting, same ``step_id`` / ``experiment_id`` linkage, MEDIUM
        priority. The ``offset_seconds`` is rendered in the title and message
        as whole minutes when it divides cleanly, otherwise as raw seconds, so
        a 600s offset reads "10 minutes" but a 90s offset reads "90 seconds".
        Stored as ``offset_seconds`` (and the human-friendly ``offset_label``)
        in metadata so the frontend can render either form without parsing
        the message.
        """
        if offset_seconds % 60 == 0 and offset_seconds >= 60:
            offset_label = f"{offset_seconds // 60} minutes"
        else:
            offset_label = f"{offset_seconds} seconds"
        return Notification(
            title=f"Pre-warning: {step.name}",
            message=(
                f"{offset_label} remaining on '{step.name}' in experiment "
                f"'{experiment.name}'."
            ),
            notification_type=NotificationType.STEP_PREWARNING,
            priority=NotificationPriority.MEDIUM,
            target_users=target_users or (
                [experiment.owner] if hasattr(experiment, 'owner') else []
            ),
            experiment_id=experiment.id,
            step_id=step.id,
            metadata={
                "offset_seconds": offset_seconds,
                "offset_label": offset_label,
            },
        )

    return {
        "step_ready": step_ready_notification,
        "step_completed": step_completed_notification,
        "resource_conflict": resource_conflict_notification,
        "user_attention": user_attention_notification,
        "step_timeout": step_timeout_notification,
        "step_prewarning": step_prewarning_notification,
    }
