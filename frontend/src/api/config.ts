/**
 * Centralized API configuration.
 *
 * The backend host previously appeared as a hardcoded `http://localhost:5001`
 * string in four files (client.ts, auth.ts, socket.ts, notifications.ts). U8
 * pulls them all here so deployments can override via the standard CRA
 * env-var mechanism.
 *
 * Usage:
 *   import { API_URL, API_BASE } from './config';
 *   axios.get(`${API_BASE}/experiments`);  // REST
 *   io(API_URL, { ... });                   // socket.io (no /api suffix)
 *
 * The two exports are siblings, not parent/child: `API_URL` is the bare host
 * for socket.io connections (which root at the host, not at /api), and
 * `API_BASE` is the REST root that always ends in /api.
 */
export const API_URL: string = process.env.REACT_APP_API_URL || 'http://localhost:5001';
export const API_BASE: string = `${API_URL}/api`;
