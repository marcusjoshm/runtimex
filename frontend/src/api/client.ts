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

  skipStep: async (stepId: string): Promise<Experiment> => {
    const response = await axios.post(`${API_URL}/steps/${stepId}/skip`);
    return response.data;
  },

  getUserExperiments: async (): Promise<Experiment[]> => {
    const response = await axios.get(`${API_URL}/user/experiments`);
    return response.data;
  },

  // Export experiment
  exportExperiment: async (experimentId: string): Promise<void> => {
    // The backend's export route is now @jwt_required (U3), so we must send
    // the Authorization header — `window.location.href` won't. Pull the
    // payload as a Blob via axios (which carries the default Authorization
    // header set by bootstrapAuth/login) and trigger the download from a
    // temporary anchor element.
    const response = await axios.get(
      `${API_URL}/experiments/${experimentId}/export`,
      { responseType: 'blob' }
    );

    const blob = new Blob([response.data], {
      type: response.headers['content-type'] || 'application/json',
    });
    const objectUrl = URL.createObjectURL(blob);

    // Try to honor Content-Disposition's filename, fall back to a sensible default.
    let filename = `experiment-${experimentId}.json`;
    const disposition = response.headers['content-disposition'];
    if (typeof disposition === 'string') {
      const match = disposition.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
      if (match && match[1]) {
        filename = decodeURIComponent(match[1]);
      }
    }

    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(objectUrl);
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