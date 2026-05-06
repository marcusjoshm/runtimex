import React from 'react';
import { Navigate } from 'react-router-dom';

interface ProtectedRouteProps {
  children: React.ReactNode;
}

/**
 * Visual auth gate. Reads the JWT from localStorage and redirects to /login
 * if absent. The backend's @jwt_required is the real authorization gate;
 * this is a UX shortcut so unauthenticated users don't briefly see protected
 * pages flash before their fetch calls 401.
 */
const ProtectedRoute: React.FC<ProtectedRouteProps> = ({ children }) => {
  const token = localStorage.getItem('token');
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
};

export default ProtectedRoute;
