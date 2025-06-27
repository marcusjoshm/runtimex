import axios from 'axios';
import { io, Socket } from 'socket.io-client';
import authClient from './auth';

const API_URL = 'http://localhost:5001/api';

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

class NotificationService {
  private socket: Socket | null = null;
  private handlers: Map<string, NotificationHandler> = new Map();
  private notificationListeners: ((notifications: Notification[]) => void)[] = [];
  private notifications: Notification[] = [];

  constructor() {
    // Initialize socket if user is logged in
    this.initSocket();

    // Listen for auth changes
    document.addEventListener('authChanged', this.initSocket);
  }

  private initSocket = async () => {
    const user = await authClient.getCurrentUser();
    
    if (user) {
      // Get JWT token
      const token = localStorage.getItem('token');
      
      // Close existing socket if it exists
      if (this.socket) {
        this.socket.disconnect();
      }
      
      // Create new socket connection with auth token
      this.socket = io('http://localhost:5001', {
        query: { token }
      });
      
      // Set up event handlers
      this.socket.on('connect', () => {
        console.log('Connected to notification service');
        this.fetchNotifications(); // Get initial notifications
      });
      
      this.socket.on('notification', (notification: Notification) => {
        console.log('Received notification:', notification);
        this.notifications.unshift(notification); // Add to start of array
        this.notifyListeners();
        
        // Call the specific handler if registered
        const handler = this.handlers.get(notification.type);
        if (handler) {
          handler(notification);
        }
      });
    } else if (this.socket) {
      // Disconnect if user logged out
      this.socket.disconnect();
      this.socket = null;
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
      const response = await axios.get(`${API_URL}/notifications${unreadOnly ? '?unread_only=true' : ''}`);
      this.notifications = response.data;
      this.notifyListeners();
      return this.notifications;
    } catch (error) {
      console.error('Failed to fetch notifications:', error);
      return [];
    }
  }

  // Mark a notification as read
  public async markAsRead(notificationId: string) {
    try {
      await axios.post(`${API_URL}/notifications/${notificationId}/read`);
      
      // Update local state
      const notification = this.notifications.find(n => n.id === notificationId);
      if (notification) {
        notification.is_read = true;
        this.notifyListeners();
      }
    } catch (error) {
      console.error('Failed to mark notification as read:', error);
    }
  }

  // Dismiss a notification
  public async dismissNotification(notificationId: string) {
    try {
      await axios.post(`${API_URL}/notifications/${notificationId}/dismiss`);
      
      // Update local state
      const notification = this.notifications.find(n => n.id === notificationId);
      if (notification) {
        notification.is_dismissed = true;
        this.notifyListeners();
      }
    } catch (error) {
      console.error('Failed to dismiss notification:', error);
    }
  }

  // Delete a notification
  public async deleteNotification(notificationId: string) {
    try {
      await axios.delete(`${API_URL}/notifications/${notificationId}`);
      
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