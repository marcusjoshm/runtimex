import axios from 'axios';

const API_URL = 'http://localhost:5001/api';

// Define interfaces to match backend models
export interface Step {
  id: string;
  name: string;
  type: string;
  duration: number;
  status: string;
  dependencies: string[];
  notes?: string;
  resourceNeeded?: string;
  scheduledStartTime?: string;
  scheduledEndTime?: string;
  actualStartTime?: string;
  actualEndTime?: string;
  elapsedTime?: number;
}

export interface Experiment {
  id: string;
  name: string;
  description: string;
  steps: Step[];
  owner?: string;
  sharedWith?: Record<string, string>; // username -> permission
}

// Create API client
const apiClient = {
  // Experiment API methods
  getExperiments: async (): Promise<Experiment[]> => {
    const response = await axios.get(`${API_URL}/experiments`);
    return response.data;
  },
  
  getExperiment: async (id: string): Promise<Experiment> => {
    const response = await axios.get(`${API_URL}/experiments/${id}`);
    return response.data;
  },
  
  createExperiment: async (experiment: Omit<Experiment, 'id'>): Promise<Experiment> => {
    const response = await axios.post(`${API_URL}/experiments`, experiment);
    return response.data;
  },
  
  updateExperiment: async (id: string, experiment: Partial<Experiment>): Promise<Experiment> => {
    const response = await axios.put(`${API_URL}/experiments/${id}`, experiment);
    return response.data;
  },
  
  // Step API methods
  startStep: async (stepId: string): Promise<Experiment> => {
    const response = await axios.post(`${API_URL}/steps/${stepId}/start`);
    return response.data;
  },
  
  pauseStep: async (stepId: string): Promise<Experiment> => {
    const response = await axios.post(`${API_URL}/steps/${stepId}/pause`);
    return response.data;
  },
  
  completeStep: async (stepId: string): Promise<Experiment> => {
    const response = await axios.post(`${API_URL}/steps/${stepId}/complete`);
    return response.data;
  },

  getUserExperiments: async (): Promise<Experiment[]> => {
    const response = await axios.get(`${API_URL}/user/experiments`);
    return response.data;
  },

  // Export experiment
  exportExperiment: async (experimentId: string): Promise<void> => {
    // This will trigger a file download
    window.location.href = `${API_URL}/experiments/${experimentId}/export`;
  },

  // Import experiment
  importExperiment: async (file: File): Promise<Experiment> => {
    const formData = new FormData();
    formData.append('file', file);
    
    const response = await axios.post(`${API_URL}/experiments/import`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    });
    return response.data;
  },

  // Template management
  getTemplates: async (): Promise<any[]> => {
    const response = await axios.get(`${API_URL}/templates`);
    return response.data;
  },

  createTemplate: async (experimentId: string, name: string): Promise<any> => {
    const response = await axios.post(`${API_URL}/templates`, {
      experimentId,
      name
    });
    return response.data;
  },

  deleteTemplate: async (templateId: string): Promise<void> => {
    await axios.delete(`${API_URL}/templates/${templateId}`);
  },

  createFromTemplate: async (templateId: string, name?: string): Promise<Experiment> => {
    const response = await axios.post(`${API_URL}/experiments/create-from-template/${templateId}`, {
      name
    });
    return response.data;
  },

  // Share experiment
  shareExperiment: async (experimentId: string, username: string, permission: 'view' | 'edit'): Promise<void> => {
    await axios.post(`${API_URL}/experiments/${experimentId}/share`, {
      username,
      permission
    });
  }
};

export default apiClient; 