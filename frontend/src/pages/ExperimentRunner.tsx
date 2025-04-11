import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Box,
  Button,
  Card,
  CardContent,
  CardActions,
  Chip,
  Container,
  Grid,
  LinearProgress,
  Paper,
  Typography,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  List,
  ListItem,
  ListItemText,
  Divider,
  IconButton,
  Alert
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import PauseIcon from '@mui/icons-material/Pause';
import CheckIcon from '@mui/icons-material/Check';
import TimerIcon from '@mui/icons-material/Timer';
import SkipNextIcon from '@mui/icons-material/SkipNext';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import ErrorIcon from '@mui/icons-material/Error';
import { format, differenceInSeconds, parseISO } from 'date-fns';
import apiClient, { Experiment, Step } from '../api/client';

// Maps to match backend enum values
const StepStatus = {
  PENDING: 'pending',
  READY: 'ready',
  RUNNING: 'running',
  PAUSED: 'paused',
  COMPLETED: 'completed',
  SKIPPED: 'skipped',
  ERROR: 'error'
} as const;

const StepType = {
  FIXED_DURATION: 'fixed_duration',
  TASK: 'task',
  FIXED_START: 'fixed_start',
  AUTOMATED_TASK: 'automated_task'
} as const;

const ExperimentRunner: React.FC = () => {
  const { experimentId } = useParams<{ experimentId: string }>();
  const navigate = useNavigate();
  
  const [experiment, setExperiment] = useState<Experiment | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState<Date>(new Date());
  const [activeStepIndex, setActiveStepIndex] = useState<number | null>(null);
  const [showConflictDialog, setShowConflictDialog] = useState(false);
  const [conflicts, setConflicts] = useState<{ step1: Step, step2: Step }[]>([]);
  const [showInfoDialog, setShowInfoDialog] = useState(false);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);

  // Fetch experiment data
  useEffect(() => {
    const fetchExperiment = async () => {
      if (!experimentId) return;
      
      try {
        setLoading(true);
        const data = await apiClient.getExperiment(experimentId);
        setExperiment(data);
        
        // Set the first READY step as active
        const readyStepIndex = data.steps.findIndex(step => step.status === StepStatus.READY);
        if (readyStepIndex !== -1) {
          setActiveStepIndex(readyStepIndex);
        }
        
        setError(null);
      } catch (err) {
        console.error('Failed to fetch experiment:', err);
        setError('Failed to load experiment. Please try again later.');
        
        // Fall back to mock data in development
        if (process.env.NODE_ENV === 'development' && experimentId === '1') {
          const now = new Date();
          
          // Create sample experiment with steps
          const mockExperiment: Experiment = {
            id: '1',
            name: 'Cell Culture Protocol',
            description: 'Standard protocol for maintaining cell cultures',
            steps: [
              {
                id: 's1',
                name: 'Prepare media',
                type: StepType.TASK,
                duration: 15,
                status: StepStatus.READY,
                dependencies: [],
                resourceNeeded: 'lab_bench',
                scheduledStartTime: now.toISOString(),
                scheduledEndTime: new Date(now.getTime() + 15 * 60 * 1000).toISOString()
              },
              {
                id: 's2',
                name: 'Thaw cells',
                type: StepType.FIXED_DURATION,
                duration: 30,
                status: StepStatus.PENDING,
                dependencies: ['s1'],
                resourceNeeded: 'water_bath',
                scheduledStartTime: new Date(now.getTime() + 15 * 60 * 1000).toISOString(),
                scheduledEndTime: new Date(now.getTime() + 45 * 60 * 1000).toISOString()
              },
              {
                id: 's3',
                name: 'Centrifuge cells',
                type: StepType.FIXED_DURATION,
                duration: 5,
                status: StepStatus.PENDING,
                dependencies: ['s2'],
                resourceNeeded: 'centrifuge',
                scheduledStartTime: new Date(now.getTime() + 45 * 60 * 1000).toISOString(),
                scheduledEndTime: new Date(now.getTime() + 50 * 60 * 1000).toISOString()
              },
              {
                id: 's4',
                name: 'Plate cells',
                type: StepType.TASK,
                duration: 20,
                status: StepStatus.PENDING,
                dependencies: ['s3'],
                resourceNeeded: 'hood',
                scheduledStartTime: new Date(now.getTime() + 50 * 60 * 1000).toISOString(),
                scheduledEndTime: new Date(now.getTime() + 70 * 60 * 1000).toISOString()
              }
            ]
          };
          
          setExperiment(mockExperiment);
          
          // Set the first READY step as active
          const readyStepIndex = mockExperiment.steps.findIndex(step => step.status === StepStatus.READY);
          if (readyStepIndex !== -1) {
            setActiveStepIndex(readyStepIndex);
          }
        }
      } finally {
        setLoading(false);
      }
    };
    
    fetchExperiment();
  }, [experimentId]);

  // Update current time every second and track elapsed time
  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date());
      
      // Update running steps with elapsed time
      if (experiment) {
        const updatedSteps = experiment.steps.map(step => {
          if (step.status === StepStatus.RUNNING && step.actualStartTime) {
            const elapsed = differenceInSeconds(new Date(), parseISO(step.actualStartTime));
            return { ...step, elapsedTime: elapsed };
          }
          return step;
        });
        
        setExperiment({ ...experiment, steps: updatedSteps });
        
        // Auto-complete fixed duration steps if they have finished
        updatedSteps.forEach((step) => {
          if (step.status === StepStatus.RUNNING && 
              step.type === StepType.FIXED_DURATION && 
              step.actualStartTime && 
              step.elapsedTime && 
              step.elapsedTime >= step.duration * 60) {
            handleStepComplete(step.id);
          }
        });
      }
    }, 1000);
    
    return () => clearInterval(timer);
  }, [experiment]);

  // Handle step actions
  const handleStepStart = async (stepId: string) => {
    if (!experiment) return;
    
    try {
      const updatedExperiment = await apiClient.startStep(stepId);
      setExperiment(updatedExperiment);
      
      // Set this step as active
      const newActiveIndex = updatedExperiment.steps.findIndex(step => step.id === stepId);
      if (newActiveIndex !== -1) {
        setActiveStepIndex(newActiveIndex);
      }
      
      // Check for conflicts (steps running at the same time that use the same resource)
      const runningSteps = updatedExperiment.steps.filter(step => step.status === StepStatus.RUNNING);
      const newConflicts = [];
      
      for (let i = 0; i < runningSteps.length; i++) {
        for (let j = i + 1; j < runningSteps.length; j++) {
          if (runningSteps[i].resourceNeeded && 
              runningSteps[i].resourceNeeded === runningSteps[j].resourceNeeded) {
            newConflicts.push({ step1: runningSteps[i], step2: runningSteps[j] });
          }
        }
      }
      
      if (newConflicts.length > 0) {
        setConflicts(newConflicts);
        setShowConflictDialog(true);
      }
    } catch (err) {
      console.error('Failed to start step:', err);
      alert('Failed to start step. Please try again.');
    }
  };

  const handleStepPause = async (stepId: string) => {
    if (!experiment) return;
    
    try {
      const updatedExperiment = await apiClient.pauseStep(stepId);
      setExperiment(updatedExperiment);
    } catch (err) {
      console.error('Failed to pause step:', err);
      alert('Failed to pause step. Please try again.');
    }
  };

  const handleStepResume = async (stepId: string) => {
    if (!experiment) return;
    
    try {
      const updatedExperiment = await apiClient.startStep(stepId); // Reuse start endpoint for resume
      setExperiment(updatedExperiment);
    } catch (err) {
      console.error('Failed to resume step:', err);
      alert('Failed to resume step. Please try again.');
    }
  };

  const handleStepComplete = async (stepId: string) => {
    if (!experiment) return;
    
    try {
      const updatedExperiment = await apiClient.completeStep(stepId);
      setExperiment(updatedExperiment);
      
      // Find next READY step and set as active
      const nextReadyIndex = updatedExperiment.steps.findIndex(step => step.status === StepStatus.READY);
      if (nextReadyIndex !== -1) {
        setActiveStepIndex(nextReadyIndex);
      } else {
        // No more ready steps
        setActiveStepIndex(null);
      }
    } catch (err) {
      console.error('Failed to complete step:', err);
      alert('Failed to complete step. Please try again.');
    }
  };

  const handleStepSkip = async (stepId: string) => {
    if (!experiment) return;
    
    try {
      // For now, just mark as completed in UI
      // In a real app, there would be a skip endpoint
      const updatedSteps = experiment.steps.map(step => {
        if (step.id === stepId) {
          return {
            ...step,
            status: StepStatus.SKIPPED
          };
        }
        return step;
      });
      
      setExperiment({...experiment, steps: updatedSteps});
      
      // Find next READY step and set as active
      const nextReadyIndex = updatedSteps.findIndex(step => step.status === StepStatus.READY);
      if (nextReadyIndex !== -1) {
        setActiveStepIndex(nextReadyIndex);
      } else {
        // No more ready steps
        setActiveStepIndex(null);
      }
    } catch (err) {
      console.error('Failed to skip step:', err);
      alert('Failed to skip step. Please try again.');
    }
  };

  const showStepDetails = (stepId: string) => {
    setSelectedStepId(stepId);
    setShowInfoDialog(true);
  };

  const getStepStatusChip = (status: string) => {
    switch (status) {
      case StepStatus.PENDING:
        return <Chip label="Pending" color="default" size="small" />;
      case StepStatus.READY:
        return <Chip label="Ready" color="primary" size="small" />;
      case StepStatus.RUNNING:
        return <Chip label="Running" color="secondary" size="small" />;
      case StepStatus.PAUSED:
        return <Chip label="Paused" color="warning" size="small" />;
      case StepStatus.COMPLETED:
        return <Chip label="Completed" color="success" size="small" icon={<CheckIcon />} />;
      case StepStatus.SKIPPED:
        return <Chip label="Skipped" color="default" size="small" icon={<SkipNextIcon />} />;
      case StepStatus.ERROR:
        return <Chip label="Error" color="error" size="small" icon={<ErrorIcon />} />;
      default:
        return <Chip label={status} size="small" />;
    }
  };

  const formatTime = (seconds?: number) => {
    if (seconds === undefined) return '--:--';
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  const getProgress = (step: Step) => {
    if (!step.elapsedTime || step.type === StepType.TASK) return 0;
    const progress = (step.elapsedTime / (step.duration * 60)) * 100;
    return Math.min(progress, 100);
  };

  const formatDateTime = (dateStr?: string) => {
    if (!dateStr) return 'Not set';
    try {
      return format(parseISO(dateStr), 'HH:mm:ss');
    } catch (e) {
      return 'Invalid date';
    }
  };

  if (loading) {
    return (
      <Container maxWidth="md">
        <Box sx={{ my: 4, textAlign: 'center' }}>
          <Typography variant="h4">Loading experiment...</Typography>
          <LinearProgress sx={{ mt: 2 }} />
        </Box>
      </Container>
    );
  }

  if (error || !experiment) {
    return (
      <Container maxWidth="md">
        <Box sx={{ my: 4, textAlign: 'center' }}>
          <Typography variant="h4" color="error">Error</Typography>
          <Typography>{error || 'Could not load experiment'}</Typography>
          <Button 
            variant="contained" 
            sx={{ mt: 2 }}
            onClick={() => navigate('/')}
          >
            Back to Home
          </Button>
        </Box>
      </Container>
    );
  }

  const activeStep = activeStepIndex !== null ? experiment.steps[activeStepIndex] : null;
  const pendingSteps = experiment.steps.filter(step => step.status === StepStatus.PENDING);
  const readySteps = experiment.steps.filter(step => step.status === StepStatus.READY);
  const runningSteps = experiment.steps.filter(step => step.status === StepStatus.RUNNING);
  const completedSteps = experiment.steps.filter(step => step.status === StepStatus.COMPLETED);
  const selectedStep = selectedStepId ? experiment.steps.find(step => step.id === selectedStepId) : null;

  const allStepsComplete = experiment.steps.every(step => 
    step.status === StepStatus.COMPLETED || step.status === StepStatus.SKIPPED);

  return (
    <Container maxWidth="lg">
      <Box sx={{ my: 4 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 3 }}>
          <IconButton onClick={() => navigate(-1)}>
            <ArrowBackIcon />
          </IconButton>
          <Typography variant="h4" component="h1">
            {experiment.name}
          </Typography>
        </Box>

        {/* Experiment Overview */}
        <Paper sx={{ p: 3, mb: 4 }}>
          <Grid container spacing={2}>
            <Grid item xs={12} md={6}>
              <Typography variant="subtitle1" gutterBottom>
                Current Time: {format(currentTime, 'HH:mm:ss')}
              </Typography>
              <Typography variant="body2">
                {experiment.description}
              </Typography>
            </Grid>
            <Grid item xs={12} md={6}>
              <Typography variant="subtitle1" gutterBottom>
                Progress: {completedSteps.length}/{experiment.steps.length} steps completed
              </Typography>
              <LinearProgress 
                variant="determinate" 
                value={(completedSteps.length / experiment.steps.length) * 100} 
                sx={{ height: 10, mb: 2 }}
              />
              
              <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                <Typography variant="body2">
                  <strong>Running:</strong> {runningSteps.length} steps
                </Typography>
                <Typography variant="body2">
                  <strong>Ready:</strong> {readySteps.length} steps
                </Typography>
                <Typography variant="body2">
                  <strong>Pending:</strong> {pendingSteps.length} steps
                </Typography>
              </Box>
              
              {allStepsComplete && (
                <Alert severity="success" sx={{ mt: 2 }}>
                  All experiment steps completed!
                </Alert>
              )}
            </Grid>
          </Grid>
        </Paper>
        
        {/* Active Step Card */}
        {activeStep && (
          <Box sx={{ mb: 4 }}>
            <Typography variant="h5" gutterBottom>
              Current Step
            </Typography>
            <Card>
              <CardContent>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
                  <Typography variant="h6">{activeStep.name}</Typography>
                  {getStepStatusChip(activeStep.status)}
                </Box>
                
                <Grid container spacing={2}>
                  <Grid item xs={12} md={6}>
                    <Typography variant="body2" color="text.secondary" gutterBottom>
                      Type: {activeStep.type.replace('_', ' ')}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" gutterBottom>
                      Duration: {activeStep.duration} minutes
                    </Typography>
                    {activeStep.resourceNeeded && (
                      <Typography variant="body2" color="text.secondary" gutterBottom>
                        Resource: {activeStep.resourceNeeded}
                      </Typography>
                    )}
                    {activeStep.notes && (
                      <Typography variant="body2" gutterBottom>
                        Notes: {activeStep.notes}
                      </Typography>
                    )}
                  </Grid>
                  <Grid item xs={12} md={6}>
                    {activeStep.status === StepStatus.RUNNING && (
                      <>
                        <Box sx={{ display: 'flex', alignItems: 'center' }}>
                          <TimerIcon sx={{ mr: 1 }} />
                          <Typography variant="h6">
                            {formatTime(activeStep.elapsedTime)}
                          </Typography>
                        </Box>
                        
                        {activeStep.type !== StepType.TASK && (
                          <LinearProgress 
                            variant="determinate" 
                            value={getProgress(activeStep)} 
                            sx={{ height: 10, mt: 1 }}
                          />
                        )}
                      </>
                    )}
                  </Grid>
                </Grid>
              </CardContent>
              <CardActions>
                {activeStep.status === StepStatus.READY && (
                  <Button 
                    color="primary" 
                    variant="contained"
                    startIcon={<PlayArrowIcon />}
                    onClick={() => handleStepStart(activeStep.id)}
                  >
                    Start Step
                  </Button>
                )}
                
                {activeStep.status === StepStatus.RUNNING && (
                  <>
                    {activeStep.type === StepType.TASK && (
                      <Button 
                        color="warning" 
                        variant="contained"
                        startIcon={<PauseIcon />}
                        onClick={() => handleStepPause(activeStep.id)}
                      >
                        Pause
                      </Button>
                    )}
                    
                    <Button 
                      color="success" 
                      variant="contained"
                      startIcon={<CheckIcon />}
                      onClick={() => handleStepComplete(activeStep.id)}
                    >
                      Complete
                    </Button>
                  </>
                )}
                
                {activeStep.status === StepStatus.PAUSED && (
                  <>
                    <Button 
                      color="primary" 
                      variant="contained"
                      startIcon={<PlayArrowIcon />}
                      onClick={() => handleStepResume(activeStep.id)}
                    >
                      Resume
                    </Button>
                    
                    <Button 
                      color="success" 
                      variant="contained"
                      startIcon={<CheckIcon />}
                      onClick={() => handleStepComplete(activeStep.id)}
                    >
                      Complete
                    </Button>
                  </>
                )}
                
                {activeStep.status !== StepStatus.COMPLETED && activeStep.status !== StepStatus.SKIPPED && (
                  <Button 
                    color="error" 
                    startIcon={<SkipNextIcon />}
                    onClick={() => handleStepSkip(activeStep.id)}
                  >
                    Skip
                  </Button>
                )}
              </CardActions>
            </Card>
          </Box>
        )}
        
        {/* Steps List */}
        <Box sx={{ mb: 4 }}>
          <Typography variant="h5" gutterBottom>
            All Steps
          </Typography>
          <List component={Paper}>
            {experiment.steps.map((step, index) => (
              <React.Fragment key={step.id}>
                {index > 0 && <Divider />}
                <ListItem
                  secondaryAction={
                    <Box>
                      {step.status === StepStatus.RUNNING && (
                        <Typography variant="body2" color="text.secondary" sx={{ mr: 2 }}>
                          {formatTime(step.elapsedTime)}
                        </Typography>
                      )}
                      {getStepStatusChip(step.status)}
                    </Box>
                  }
                  onClick={() => showStepDetails(step.id)}
                  sx={{ cursor: 'pointer' }}
                >
                  <ListItemText
                    primary={`${index + 1}. ${step.name}`}
                    secondary={`Type: ${step.type.replace('_', ' ')} | Duration: ${step.duration} min | Resource: ${step.resourceNeeded || 'none'}`}
                  />
                </ListItem>
              </React.Fragment>
            ))}
          </List>
        </Box>
      </Box>
      
      {/* Conflict Dialog */}
      <Dialog
        open={showConflictDialog}
        onClose={() => setShowConflictDialog(false)}
      >
        <DialogTitle>Resource Conflict Detected</DialogTitle>
        <DialogContent>
          <DialogContentText>
            The following steps are trying to use the same resources at the same time:
          </DialogContentText>
          <List>
            {conflicts.map((conflict, index) => (
              <ListItem key={index}>
                <ListItemText
                  primary={`Conflict: ${conflict.step1.name} and ${conflict.step2.name}`}
                  secondary={`Both need ${conflict.step1.resourceNeeded}`}
                />
              </ListItem>
            ))}
          </List>
          <DialogContentText>
            Consider pausing one of the steps or rescheduling.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowConflictDialog(false)}>
            Acknowledge
          </Button>
        </DialogActions>
      </Dialog>
      
      {/* Step Info Dialog */}
      <Dialog
        open={showInfoDialog}
        onClose={() => setShowInfoDialog(false)}
      >
        <DialogTitle>Step Details</DialogTitle>
        <DialogContent>
          {selectedStep && (
            <>
              <Typography variant="h6" gutterBottom>{selectedStep.name}</Typography>
              <Typography variant="body2" gutterBottom>
                <strong>Type:</strong> {selectedStep.type.replace('_', ' ')}
              </Typography>
              <Typography variant="body2" gutterBottom>
                <strong>Duration:</strong> {selectedStep.duration} minutes
              </Typography>
              <Typography variant="body2" gutterBottom>
                <strong>Status:</strong> {selectedStep.status}
              </Typography>
              {selectedStep.resourceNeeded && (
                <Typography variant="body2" gutterBottom>
                  <strong>Resource Needed:</strong> {selectedStep.resourceNeeded}
                </Typography>
              )}
              {selectedStep.dependencies.length > 0 && (
                <Typography variant="body2" gutterBottom>
                  <strong>Dependencies:</strong> {selectedStep.dependencies.map(depId => {
                    const depStep = experiment.steps.find(s => s.id === depId);
                    return depStep ? depStep.name : depId;
                  }).join(', ')}
                </Typography>
              )}
              {selectedStep.notes && (
                <Typography variant="body2" gutterBottom>
                  <strong>Notes:</strong> {selectedStep.notes}
                </Typography>
              )}
              <Typography variant="body2" gutterBottom>
                <strong>Scheduled Start:</strong> {formatDateTime(selectedStep.scheduledStartTime)}
              </Typography>
              <Typography variant="body2" gutterBottom>
                <strong>Actual Start:</strong> {formatDateTime(selectedStep.actualStartTime)}
              </Typography>
              {selectedStep.actualEndTime && (
                <Typography variant="body2" gutterBottom>
                  <strong>Actual End:</strong> {formatDateTime(selectedStep.actualEndTime)}
                </Typography>
              )}
            </>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowInfoDialog(false)}>Close</Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
};

export default ExperimentRunner; 