import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import Box from '@mui/material/Box';

// Pages
import Home from './pages/Home';
import ExperimentDesigner from './pages/ExperimentDesigner';
import ExperimentRunner from './pages/ExperimentRunner';
import WatchView from './pages/WatchView';
import Login from './pages/Login';
import Register from './pages/Register';
import AppHeader from './components/AppHeader';
import ProtectedRoute from './components/ProtectedRoute';

// Theme
const theme = createTheme({
  palette: {
    primary: {
      main: '#2196f3',
    },
    secondary: {
      main: '#f50057',
    },
  },
});

function App() {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Router>
        <Routes>
          {/* Auth routes */}
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          
          {/* Watch view route - no header, full screen */}
          <Route
            path="/watch/:experimentId"
            element={
              <ProtectedRoute>
                <WatchView />
              </ProtectedRoute>
            }
          />

          {/* Regular app routes with header */}
          <Route path="*" element={
            <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
              <AppHeader />
              <Box component="main" sx={{ flexGrow: 1, p: 3 }}>
                <Routes>
                  <Route path="/" element={<Home />} />
                  <Route
                    path="/design"
                    element={
                      <ProtectedRoute>
                        <ExperimentDesigner />
                      </ProtectedRoute>
                    }
                  />
                  <Route
                    path="/design/:id"
                    element={
                      <ProtectedRoute>
                        <ExperimentDesigner />
                      </ProtectedRoute>
                    }
                  />
                  <Route
                    path="/run/:experimentId"
                    element={
                      <ProtectedRoute>
                        <ExperimentRunner />
                      </ProtectedRoute>
                    }
                  />
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
              </Box>
            </Box>
          } />
        </Routes>
      </Router>
    </ThemeProvider>
  );
}

export default App; 