import { io, Socket } from 'socket.io-client';
import { Experiment } from './client';
import { API_URL } from './config';

/**
 * Shared socket.io instance for the whole frontend.
 *
 * U8 consolidated what used to be two parallel connections (one here for
 * experiment_update, one in notifications.ts for notification events) into
 * one. The notification module now subscribes to the `notification` event
 * on this shared instance via {@link onNotification}.
 *
 * Token transport: U1's server-side connect handler validates the JWT via
 * `verify_jwt_in_request(locations=['query_string'])`, so we keep passing
 * the token via socket.io's `query` option here. Switching to socket.io's
 * `auth` option is a known follow-up that requires a coordinated server
 * change; this unit deliberately doesn't take that on. Documented in the
 * U8 implementation report.
 */
class SocketService {
  private socket: Socket | null = null;
  private experimentUpdateHandlers: Array<(experiment: Experiment) => void> = [];
  private notificationHandlers: Array<(notification: any) => void> = [];

  initializeSocket() {
    if (this.socket?.connected) return;

    const token = localStorage.getItem('token');

    this.socket = io(API_URL, {
      query: { token },
      autoConnect: true
    });

    this.socket.on('connect', () => {
      console.log('Socket connected');
    });

    this.socket.on('disconnect', () => {
      console.log('Socket disconnected');
    });

    this.socket.on('experiment_update', (experiment: Experiment) => {
      this.experimentUpdateHandlers.forEach(handler => handler(experiment));
    });

    // Notification events fan out to whoever subscribed via onNotification.
    // notifications.ts is the primary consumer; it stays decoupled from
    // socket creation so we can have exactly one connection per tab.
    this.socket.on('notification', (notification: any) => {
      this.notificationHandlers.forEach(handler => handler(notification));
    });
  }

  disconnectSocket() {
    if (this.socket) {
      this.socket.disconnect();
      this.socket = null;
    }
  }

  startExperimentUpdates(experimentId: string) {
    if (this.socket) {
      this.socket.emit('join_experiment', experimentId);
    }
  }

  stopExperimentUpdates(experimentId: string) {
    if (this.socket) {
      this.socket.emit('leave_experiment', experimentId);
    }
  }

  onExperimentUpdate(handler: (experiment: Experiment) => void) {
    this.experimentUpdateHandlers.push(handler);

    // Return unsubscribe function
    return () => {
      const index = this.experimentUpdateHandlers.indexOf(handler);
      if (index > -1) {
        this.experimentUpdateHandlers.splice(index, 1);
      }
    };
  }

  /**
   * Subscribe to `notification` events on the shared socket. Returns an
   * unsubscribe function. Used by notifications.ts so the whole app
   * shares one socket connection (U8).
   */
  onNotification(handler: (notification: any) => void) {
    this.notificationHandlers.push(handler);

    return () => {
      const index = this.notificationHandlers.indexOf(handler);
      if (index > -1) {
        this.notificationHandlers.splice(index, 1);
      }
    };
  }

  emit(event: string, data: any) {
    if (this.socket) {
      this.socket.emit(event, data);
    }
  }

  on(event: string, handler: (data: any) => void) {
    if (this.socket) {
      this.socket.on(event, handler);
    }
  }
}

const socketService = new SocketService();
export default socketService;
