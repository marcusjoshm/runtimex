import { io, Socket } from 'socket.io-client';
import { Experiment } from './client';

class SocketService {
  private socket: Socket | null = null;
  private experimentUpdateHandlers: Array<(experiment: Experiment) => void> = [];

  initializeSocket() {
    if (this.socket?.connected) return;

    const token = localStorage.getItem('token');
    
    this.socket = io('http://localhost:5001', {
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

    this.socket.on('notification', (notification: any) => {
      console.log('Notification received:', notification);
      // Handle notifications here if needed
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