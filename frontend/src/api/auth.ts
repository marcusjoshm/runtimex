import axios from 'axios';

const API_URL = 'http://localhost:5001/api';

export interface User {
  id: string;
  username: string;
  email: string;
}

export interface AuthResponse {
  message: string;
  user: User;
  token: string;
}

// Create auth client
const authClient = {
  register: async (username: string, email: string, password: string): Promise<AuthResponse> => {
    const response = await axios.post(`${API_URL}/auth/register`, {
      username,
      email,
      password
    });
    
    // Store the token
    const { token } = response.data;
    localStorage.setItem('token', token);
    
    // Set default auth header for future requests
    axios.defaults.headers.common['Authorization'] = `Bearer ${token}`;
    
    return response.data;
  },
  
  login: async (username: string, password: string): Promise<AuthResponse> => {
    const response = await axios.post(`${API_URL}/auth/login`, {
      username,
      password
    });
    
    // Store the token
    const { token } = response.data;
    localStorage.setItem('token', token);
    
    // Set default auth header for future requests
    axios.defaults.headers.common['Authorization'] = `Bearer ${token}`;
    
    return response.data;
  },
  
  logout: () => {
    localStorage.removeItem('token');
    delete axios.defaults.headers.common['Authorization'];
  },
  
  getCurrentUser: async (): Promise<User | null> => {
    const token = localStorage.getItem('token');
    if (!token) return null;
    
    try {
      // Set auth header
      axios.defaults.headers.common['Authorization'] = `Bearer ${token}`;
      
      const response = await axios.get(`${API_URL}/auth/me`);
      return response.data.user;
    } catch (error) {
      // Token might be invalid
      localStorage.removeItem('token');
      delete axios.defaults.headers.common['Authorization'];
      return null;
    }
  },
  
  isAuthenticated: (): boolean => {
    return !!localStorage.getItem('token');
  }
};

export default authClient; 