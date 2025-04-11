import axios from 'axios';

const API_URL = 'http://localhost:5000/api';

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
  }
};

export default apiClient; 