import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { Box, Typography, Button, CircularProgress } from '@mui/material';
import apiClient, { Experiment, Step } from '../api/client';
import socketService from '../api/socket';

// Status constants
const StepStatus = {
  PENDING: 'pending',
  READY: 'ready',
  RUNNING: 'running',
  PAUSED: 'paused',
  COMPLETED: 'completed',
  SKIPPED: 'skipped',
  ERROR: 'error'
};

const WatchView: React.FC = () => {
  const { experimentId } = useParams<{ experimentId: string }>();
  const [experiment, setExperiment] = useState<Experiment | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeStep, setActiveStep] = useState<Step | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  // Fetch experiment data and initialize socket
  useEffect(() => {
    if (!experimentId) return;

    const fetchExperiment = async () => {
      try {
        setLoading(true);
        const data = await apiClient.getExperiment(experimentId);
        setExperiment(data);
        
        // Find the current active step (RUNNING or first READY)
        const runningStep = data.steps.find(step => step.status === StepStatus.RUNNING);
        const readyStep = data.steps.find(step => step.status === StepStatus.READY);
        setActiveStep(runningStep || readyStep || null);
        
        setLoading(false);
      } catch (err) {
        console.error('Failed to fetch experiment:', err);
        setLoading(false);
      }
    };

    fetchExperiment();
    
    // Set up socket connection
    socketService.initializeSocket();
    socketService.startExperimentUpdates(experimentId);
    
    const unsubscribe = socketService.onExperimentUpdate((updatedExperiment) => {
      if (updatedExperiment.id === experimentId) {
        setExperiment(updatedExperiment);
        
        // Update active step
        const runningStep = updatedExperiment.steps.find(step => step.status === StepStatus.RUNNING);
        const readyStep = updatedExperiment.steps.find(step => step.status === StepStatus.READY);
        setActiveStep(runningStep || readyStep || null);
      }
    });
    
    return () => {
      unsubscribe();
      socketService.disconnectSocket();
    };
  }, [experimentId]);

  // Update timer
  useEffect(() => {
    if (!activeStep || activeStep.status !== StepStatus.RUNNING) {
      setElapsedSeconds(0);
      return;
    }
    
    // Calculate initial elapsed time if step is already running
    if (activeStep.actualStartTime) {
      const startTime = new Date(activeStep.actualStartTime).getTime();
      const now = new Date().getTime();
      setElapsedSeconds(Math.floor((now - startTime) / 1000));
    }
    
    const interval = setInterval(() => {
      setElapsedSeconds(prev => prev + 1);
    }, 1000);
    
    return () => clearInterval(interval);
  }, [activeStep]);

  // Format time as MM:SS
  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  // Handle step actions
  const handleActionButton = async () => {
    if (!activeStep || !experimentId) return;
    
    try {
      if (activeStep.status === StepStatus.READY) {
        await apiClient.startStep(activeStep.id);
      } else if (activeStep.status === StepStatus.RUNNING) {
        await apiClient.pauseStep(activeStep.id);
      } else if (activeStep.status === StepStatus.PAUSED) {
        await apiClient.startStep(activeStep.id);
      }
    } catch (err) {
      console.error('Failed to perform action:', err);
    }
  };

  const handleComplete = async () => {
    if (!activeStep || !experimentId) return;
    
    try {
      if (activeStep.status === StepStatus.RUNNING || activeStep.status === StepStatus.PAUSED) {
        await apiClient.completeStep(activeStep.id);
      }
    } catch (err) {
      console.error('Failed to complete step:', err);
    }
  };

  // Get button text based on step status
  const getActionButtonText = () => {
    if (!activeStep) return 'No Step';
    
    switch (activeStep.status) {
      case StepStatus.READY:
        return 'Start';
      case StepStatus.RUNNING:
        return 'Pause';
      case StepStatus.PAUSED:
        return 'Resume';
      default:
        return 'N/A';
    }
  };

  if (loading) {
    return (
      <Box sx={{ 
        display: 'flex', 
        flexDirection: 'column', 
        alignItems: 'center', 
        justifyContent: 'center', 
        minHeight: '100vh',
        backgroundColor: '#000',
        color: '#fff'
      }}>
        <CircularProgress color="inherit" size={40} />
      </Box>
    );
  }

  return (
    <Box sx={{ 
      display: 'flex', 
      flexDirection: 'column', 
      alignItems: 'center', 
      justifyContent: 'center', 
      minHeight: '100vh',
      padding: '8px',
      backgroundColor: '#000',
      color: '#fff'
    }}>
      {activeStep ? (
        <>
          {/* Step Name - Large and Clear */}
          <Typography variant="h6" sx={{ 
            fontSize: { xs: '18px', sm: '24px' }, 
            textAlign: 'center',
            mb: 1
          }}>
            {activeStep.name}
          </Typography>
          
          {/* Timer Display - Very Prominent */}
          <Typography variant="h1" sx={{ 
            fontSize: { xs: '48px', sm: '72px' },
            fontWeight: 'bold',
            mb: 2
          }}>
            {activeStep.status === StepStatus.RUNNING ? formatTime(elapsedSeconds) : '--:--'}
          </Typography>
          
          {/* Action Button - Large Touch Target */}
          <Button
            variant="contained"
            color={activeStep.status === StepStatus.RUNNING ? "secondary" : "primary"}
            size="large"
            disabled={!([StepStatus.READY, StepStatus.RUNNING, StepStatus.PAUSED].includes(activeStep.status as any))}
            onClick={handleActionButton}
            sx={{ 
              fontSize: { xs: '24px', sm: '30px' },
              width: { xs: '80%', sm: '60%' },
              height: '60px',
              mb: 2,
              borderRadius: '30px'
            }}
          >
            {getActionButtonText()}
          </Button>
          
          {/* Complete Button - Only Show for Running/Paused Steps */}
          {(activeStep.status === StepStatus.RUNNING || activeStep.status === StepStatus.PAUSED) && (
            <Button
              variant="outlined"
              color="success"
              size="large"
              onClick={handleComplete}
              sx={{ 
                fontSize: { xs: '20px', sm: '24px' },
                width: { xs: '80%', sm: '60%' },
                height: '50px',
                borderRadius: '25px'
              }}
            >
              Complete
            </Button>
          )}
        </>
      ) : (
        <Typography variant="h6" sx={{ textAlign: 'center' }}>
          No active step
        </Typography>
      )}
    </Box>
  );
};

export default WatchView; 