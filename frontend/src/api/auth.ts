import axios from 'axios';

const API_URL = 'http://localhost:5000/api';

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
}; 