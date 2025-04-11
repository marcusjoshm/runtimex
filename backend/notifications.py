from enum import Enum
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
import json

# Define notification types
class NotificationType(Enum):
    STEP_READY = "step_ready"
    STEP_COMPLETED = "step_completed"
    STEP_PAUSED = "step_paused"
    STEP_TIMEOUT = "step_timeout"
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
    def __init__(self, socketio=None):
        self.notifications: Dict[str, Notification] = {}  # id -> notification
        self.user_notifications: Dict[str, List[str]] = {}  # username -> [notification_ids]
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
    
    def create_notification(self, notification: Notification) -> str:
        """Create a new notification and store it"""
        self.notifications[notification.id] = notification
        
        # Associate with users
        for user in notification.target_users:
            if user not in self.user_notifications:
                self.user_notifications[user] = []
            self.user_notifications[user].append(notification.id)
        
        # Execute the handler for this notification type
        if notification.type in self.notification_handlers:
            self.notification_handlers[notification.type](notification)
        
        # Send real-time update via WebSocket if available
        if self.socketio:
            for user in notification.target_users:
                self.socketio.emit(
                    'notification', 
                    notification.to_dict(), 
                    room=f'user_{user}'
                )
        
        return notification.id
    
    def get_user_notifications(self, username: str, unread_only: bool = False) -> List[Notification]:
        """Get all notifications for a user"""
        notification_ids = self.user_notifications.get(username, [])
        result = []
        
        for nid in notification_ids:
            if nid in self.notifications:
                notification = self.notifications[nid]
                if not unread_only or not notification.is_read:
                    result.append(notification)
        
        # Sort by creation time (newest first)
        result.sort(key=lambda n: n.created_at, reverse=True)
        return result
    
    def mark_as_read(self, notification_id: str) -> bool:
        """Mark a notification as read"""
        if notification_id in self.notifications:
            self.notifications[notification_id].is_read = True
            return True
        return False
    
    def mark_as_dismissed(self, notification_id: str) -> bool:
        """Mark a notification as dismissed"""
        if notification_id in self.notifications:
            self.notifications[notification_id].is_dismissed = True
            return True
        return False
    
    def delete_notification(self, notification_id: str) -> bool:
        """Delete a notification"""
        if notification_id in self.notifications:
            notification = self.notifications[notification_id]
            
            # Remove from user associations
            for user in notification.target_users:
                if user in self.user_notifications and notification_id in self.user_notifications[user]:
                    self.user_notifications[user].remove(notification_id)
            
            # Remove the notification
            del self.notifications[notification_id]
            return True
        return False
    
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
    
    return {
        "step_ready": step_ready_notification,
        "step_completed": step_completed_notification,
        "resource_conflict": resource_conflict_notification,
        "user_attention": user_attention_notification,
        "step_timeout": step_timeout_notification
    } 