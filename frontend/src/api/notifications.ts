import axios from 'axios';
import authClient from './auth';
import socketService from './socket';
import { API_BASE } from './config';

// Notification types
export enum NotificationType {
  STEP_READY = 'step_ready',
  STEP_COMPLETED = 'step_completed',
  STEP_PAUSED = 'step_paused',
  STEP_TIMEOUT = 'step_timeout',
  RESOURCE_CONFLICT = 'resource_conflict',
  USER_ATTENTION_REQUIRED = 'user_attention_required',
  GENERAL_INFO = 'general_info',
  ERROR = 'error',
  CUSTOM = 'custom'
}

// Notification priorities
export enum NotificationPriority {
  LOW = 'low',
  MEDIUM = 'medium',
  HIGH = 'high',
  CRITICAL = 'critical'
}

// Action types
export enum ActionType {
  LINK = 'link',
  BUTTON = 'button',
  FORM = 'form',
  DISMISS = 'dismiss',
  SNOOZE = 'snooze'
}

// Action interface
export interface NotificationAction {
  id: string;
  type: ActionType;
  label: string;
  data?: Record<string, any>;
}

// Notification interface
export interface Notification {
  id: string;
  title: string;
  message: string;
  type: NotificationType;
  priority: NotificationPriority;
  target_users: string[];
  experiment_id?: string;
  step_id?: string;
  metadata?: Record<string, any>;
  actions: NotificationAction[];
  delivery_methods: string[];
  created_at: string;
  is_read: boolean;
  is_dismissed: boolean;
}

// Notification handlers type
export type NotificationHandler = (notification: Notification) => void;

/**
 * NotificationService -- thin REST + event-listener wrapper around the
 * shared socket from socket.ts. U8 consolidated what used to be a SECOND
 * socket.io connection here into a subscription on the shared instance, so
 * each browser tab now opens exactly one socket per session.
 */
class NotificationService {
  private handlers: Map<string, NotificationHandler> = new Map();
  private notificationListeners: ((notifications: Notification[]) => void)[] = [];
  private notifications: Notification[] = [];
  private unsubscribeSocket: (() => void) | null = null;

  constructor() {
    // Initialize shared-socket subscription if user is logged in
    this.initSocket();

    // Listen for auth changes (login/logout) so we re-fetch on auth flip.
    document.addEventListener('authChanged', this.initSocket);
  }

  private initSocket = async () => {
    const user = await authClient.getCurrentUser();

    if (user) {
      // Reuse the shared socket. socketService.initializeSocket is idempotent
      // (early-returns if already connected) so calling it here is safe and
      // ensures the connection exists before we subscribe.
      socketService.initializeSocket();

      // Tear down any prior subscription so we don't double-handle on auth flip.
      if (this.unsubscribeSocket) {
        this.unsubscribeSocket();
        this.unsubscribeSocket = null;
      }

      this.unsubscribeSocket = socketService.onNotification((notification: Notification) => {
        // Add to start of array via mapped-array pattern (see markAsRead/dismissNotification
        // for full context on why mutation-in-place is forbidden).
        this.notifications = [notification, ...this.notifications];

        this.notifyListeners();

        // Call the specific handler if registered
        const handler = this.handlers.get(notification.type);
        if (handler) {
          handler(notification);
        }
      });

      // Initial fetch.
      this.fetchNotifications();
    } else if (this.unsubscribeSocket) {
      // User logged out: unsubscribe so a stale handler doesn't leak.
      this.unsubscribeSocket();
      this.unsubscribeSocket = null;
    }
  };

  // Register a handler for a specific notification type
  public registerHandler(type: NotificationType, handler: NotificationHandler) {
    this.handlers.set(type, handler);
  }

  // Unregister a handler
  public unregisterHandler(type: NotificationType) {
    this.handlers.delete(type);
  }

  // Add a listener for all notifications
  public addListener(listener: (notifications: Notification[]) => void) {
    this.notificationListeners.push(listener);
    // Initial call with current notifications
    listener([...this.notifications]);
    return () => this.removeListener(listener);
  }

  // Remove a listener
  public removeListener(listener: (notifications: Notification[]) => void) {
    const index = this.notificationListeners.indexOf(listener);
    if (index !== -1) {
      this.notificationListeners.splice(index, 1);
    }
  }

  // Notify all listeners
  private notifyListeners() {
    for (const listener of this.notificationListeners) {
      listener([...this.notifications]);
    }
  }

  // Fetch notifications from the server
  public async fetchNotifications(unreadOnly = false) {
    try {
      const response = await axios.get(`${API_BASE}/notifications${unreadOnly ? '?unread_only=true' : ''}`);
      this.notifications = response.data;
      this.notifyListeners();
      return this.notifications;
    } catch (error) {
      console.error('Failed to fetch notifications:', error);
      return [];
    }
  }

  // Mark a notification as read.
  //
  // U7 audit-fix: previously this mutated ``notification.is_read`` in place
  // before notifying listeners, so ``setNotifications(newNotifications)`` in
  // a React listener received the SAME array reference and skipped re-render.
  // We now build a fresh array with a fresh notification object so listeners
  // see a different reference and re-render. NOTE FOR U8: U8 will rename the
  // wire format and consolidate the two socket connections in this file --
  // preserve this mapped-array shape; do not regress to mutate-in-place.
  public async markAsRead(notificationId: string) {
    try {
      await axios.post(`${API_BASE}/notifications/${notificationId}/read`);

      // Update local state with a NEW array + NEW object for the changed entry.
      this.notifications = Array.isArray(this.notifications)
        ? this.notifications.map(n =>
            n.id === notificationId ? { ...n, is_read: true } : n
          )
        : this.notifications;
      this.notifyListeners();
    } catch (error) {
      console.error('Failed to mark notification as read:', error);
    }
  }

  // Dismiss a notification.
  //
  // U7 audit-fix: same in-place mutation bug as ``markAsRead`` above. See
  // that comment for context. NOTE FOR U8: keep the mapped-array pattern.
  public async dismissNotification(notificationId: string) {
    try {
      await axios.post(`${API_BASE}/notifications/${notificationId}/dismiss`);

      // Update local state with a NEW array + NEW object for the changed entry.
      this.notifications = Array.isArray(this.notifications)
        ? this.notifications.map(n =>
            n.id === notificationId ? { ...n, is_dismissed: true } : n
          )
        : this.notifications;
      this.notifyListeners();
    } catch (error) {
      console.error('Failed to dismiss notification:', error);
    }
  }

  // Delete a notification
  public async deleteNotification(notificationId: string) {
    try {
      await axios.delete(`${API_BASE}/notifications/${notificationId}`);

      // Update local state
      const index = this.notifications.findIndex(n => n.id === notificationId);
      if (index !== -1) {
        this.notifications.splice(index, 1);
        this.notifyListeners();
      }
    } catch (error) {
      console.error('Failed to delete notification:', error);
    }
  }

  // Execute an action for a notification
  public async executeAction(notification: Notification, action: NotificationAction) {
    switch (action.type) {
      case ActionType.LINK:
        // Navigate to link
        if (action.data?.link) {
          window.location.href = action.data.link;
        }
        break;

      case ActionType.BUTTON:
        // Handle different button actions
        if (action.id === 'start_step' && action.data?.step_id) {
          try {
            const apiClient = (await import('./client')).default;
            await apiClient.startStep(action.data.step_id);
            this.dismissNotification(notification.id);
          } catch (error) {
            console.error('Failed to start step:', error);
          }
        } else if (action.id === 'resume_step' && action.data?.step_id) {
          try {
            const apiClient = (await import('./client')).default;
            await apiClient.startStep(action.data.step_id);
            this.dismissNotification(notification.id);
          } catch (error) {
            console.error('Failed to resume step:', error);
          }
        } else if (action.id === 'complete_step' && action.data?.step_id) {
          try {
            const apiClient = (await import('./client')).default;
            await apiClient.completeStep(action.data.step_id);
            this.dismissNotification(notification.id);
          } catch (error) {
            console.error('Failed to complete step:', error);
          }
        } else if (action.id === 'pause_step' && action.data?.step_id) {
          try {
            const apiClient = (await import('./client')).default;
            await apiClient.pauseStep(action.data.step_id);
            this.dismissNotification(notification.id);
          } catch (error) {
            console.error('Failed to pause step:', error);
          }
        }
        break;

      case ActionType.DISMISS:
        // Just dismiss the notification
        this.dismissNotification(notification.id);
        break;

      // Additional action types can be handled here

      default:
        console.warn(`Unhandled action type: ${action.type}`);
    }
  }
}

// Create singleton instance
const notificationService = new NotificationService();
export default notificationService;
