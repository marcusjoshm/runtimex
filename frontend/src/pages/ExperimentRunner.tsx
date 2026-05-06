import React, { useState, useEffect, useRef, useCallback } from 'react';
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
import apiClient, { Experiment, Step, Conflict } from '../api/client';
import socketService from '../api/socket';

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
  // Conflicts come from the backend's `Scheduler.check_for_conflicts` (U6).
  // We refresh on mount and after every `experiment_update` socket push so
  // the warning Alert stays in sync with the current schedule. The previous
  // client-side check inside `handleStepStart` is removed -- it duplicated
  // server logic and produced a double-dialog when both fired.
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [showInfoDialog, setShowInfoDialog] = useState(false);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);

  // ``experimentRef`` exists so the once-per-mount tick interval below can
  // read the latest experiment without listing it as an effect dependency.
  // Without it, the interval would tear down + rebuild every second a step
  // is RUNNING (the audit's runaway-tick bug). The companion effect below
  // keeps the ref synced on every render.
  const experimentRef = useRef<Experiment | null>(null);
  useEffect(() => {
    experimentRef.current = experiment;
  }, [experiment]);

  // Initialize socket connection
  useEffect(() => {
    // Initialize the socket connection
    socketService.initializeSocket();
    
    // Clean up on unmount
    return () => {
      socketService.disconnectSocket();
    };
  }, []);

  // Subscribe to experiment updates
  useEffect(() => {
    if (!experimentId) return;

    // Start receiving updates for this experiment
    socketService.startExperimentUpdates(experimentId);

    // Register handler for experiment updates
    const unsubscribe = socketService.onExperimentUpdate((updatedExperiment) => {
      // Only update if it's the current experiment
      if (updatedExperiment.id === experimentId) {
        setExperiment(updatedExperiment);

        // Update active step index if needed
        const readyStepIndex = updatedExperiment.steps.findIndex(step => step.status === StepStatus.READY);
        if (readyStepIndex !== -1 && activeStepIndex === null) {
          setActiveStepIndex(readyStepIndex);
        }

        // Re-fetch conflicts. A step state transition can change which steps
        // are READY/RUNNING -- a future U7 may emit notifications based on
        // the same list, so keep this Alert source-of-truth aligned with the
        // server's view. Errors here are non-fatal: silently fall back to
        // showing whatever conflicts we last fetched.
        apiClient.getConflicts(experimentId)
          .then(setConflicts)
          .catch((err) => console.error('Failed to refresh conflicts:', err));
      }
    });

    // Clean up subscription
    return unsubscribe;
  }, [experimentId, activeStepIndex]);

  // Initial conflict fetch on mount. The socket handler above keeps it
  // refreshed, but the first paint also needs them.
  useEffect(() => {
    if (!experimentId) return;
    apiClient.getConflicts(experimentId)
      .then(setConflicts)
      .catch((err) => console.error('Failed to fetch conflicts:', err));
  }, [experimentId]);

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
          
          // Create sample experiment with steps. Wire format is snake_case +
          // duration in seconds (U8); the mock matches the real shape.
          const mockExperiment: Experiment = {
            id: '1',
            name: 'Cell Culture Protocol',
            description: 'Standard protocol for maintaining cell cultures',
            steps: [
              {
                id: 's1',
                name: 'Prepare media',
                step_type: StepType.TASK,
                duration_seconds: 15 * 60,
                status: StepStatus.READY,
                dependencies: [],
                resource_required: 'lab_bench',
                scheduled_start_time: now.toISOString(),
                scheduled_end_time: new Date(now.getTime() + 15 * 60 * 1000).toISOString()
              },
              {
                id: 's2',
                name: 'Thaw cells',
                step_type: StepType.FIXED_DURATION,
                duration_seconds: 30 * 60,
                status: StepStatus.PENDING,
                dependencies: ['s1'],
                resource_required: 'water_bath',
                scheduled_start_time: new Date(now.getTime() + 15 * 60 * 1000).toISOString(),
                scheduled_end_time: new Date(now.getTime() + 45 * 60 * 1000).toISOString()
              },
              {
                id: 's3',
                name: 'Centrifuge cells',
                step_type: StepType.FIXED_DURATION,
                duration_seconds: 5 * 60,
                status: StepStatus.PENDING,
                dependencies: ['s2'],
                resource_required: 'centrifuge',
                scheduled_start_time: new Date(now.getTime() + 45 * 60 * 1000).toISOString(),
                scheduled_end_time: new Date(now.getTime() + 50 * 60 * 1000).toISOString()
              },
              {
                id: 's4',
                name: 'Plate cells',
                step_type: StepType.TASK,
                duration_seconds: 20 * 60,
                status: StepStatus.PENDING,
                dependencies: ['s3'],
                resource_required: 'hood',
                scheduled_start_time: new Date(now.getTime() + 50 * 60 * 1000).toISOString(),
                scheduled_end_time: new Date(now.getTime() + 70 * 60 * 1000).toISOString()
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

  // Auto-complete handler kept stable via useCallback so the timer effect
  // below can list it in deps without re-creating the interval. The actual
  // interval reads experiment via a ref, not the closure.
  const handleStepComplete = useCallback(async (stepId: string) => {
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
  }, []);

  // Stable ref to the latest handleStepComplete so the once-per-mount
  // interval below never closes over a stale callback.
  const handleStepCompleteRef = useRef(handleStepComplete);
  useEffect(() => {
    handleStepCompleteRef.current = handleStepComplete;
  }, [handleStepComplete]);

  // U4 pre-warnings: track which (stepId, offset) pairs we've ALREADY emitted
  // during the lifetime of this Runner mount. The server's ``prewarnings_fired``
  // list is the durable source of truth, but its update arrives via the next
  // ``experiment_update`` socket push; until that push lands we'd otherwise
  // re-emit on every tick. This local set bridges the latency: a tick after
  // an emit checks the set first and doesn't re-fire even before the server
  // round-trips the new state. Cleared on unmount; on reconnect / remount the
  // server's prewarnings_fired list is the dedupe authority anyway.
  const localPrewarningEmits = useRef<Set<string>>(new Set());

  // Per-second tick: refresh ``currentTime`` so the running-step elapsed
  // counter re-renders, and auto-complete any FIXED_DURATION step that has
  // run past its budget.
  //
  // We deliberately use ``[]`` deps and read the latest ``experiment`` from
  // a ref. The previous implementation depended on ``experiment`` and called
  // ``setExperiment`` inside the tick, which triggered a re-render -> effect
  // teardown -> new interval every single second (the audit's runaway-tick
  // bug). Now the interval is created exactly once on mount and torn down
  // on unmount.
  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date());

      const current = experimentRef.current;
      if (!current) return;

      // Auto-complete fixed-duration steps whose elapsed seconds have hit
      // their budget. We compute elapsed from actual_start_time each tick so
      // we don't rely on the server for sub-second polling. duration_seconds
      // is already in seconds (U8) so the comparison is direct -- no `* 60`.
      current.steps.forEach((step) => {
        if (
          step.status === StepStatus.RUNNING &&
          step.step_type === StepType.FIXED_DURATION &&
          step.actual_start_time
        ) {
          const elapsed = differenceInSeconds(new Date(), parseISO(step.actual_start_time));
          if (elapsed >= step.duration_seconds) {
            handleStepCompleteRef.current(step.id);
          }
        }

        // U4 pre-warnings: client-fires + server-dedupes. For any RUNNING
        // step with declared offsets that haven't yet fired, check whether
        // ``secondsRemaining <= offset`` and emit ``prewarning_hit``. We
        // rely on the same per-tick currentTime advance the auto-complete
        // logic uses; no extra setInterval needed.
        //
        // Three skip cases per offset:
        //   1. server-confirmed in step.prewarnings_fired (post-broadcast)
        //   2. locally emitted this mount (pre-broadcast latency window)
        //   3. step isn't actually RUNNING (PENDING / READY etc.)
        if (
          step.status === StepStatus.RUNNING &&
          step.actual_start_time &&
          step.prewarning_offsets_seconds &&
          step.prewarning_offsets_seconds.length > 0
        ) {
          const elapsedSinceStart = differenceInSeconds(
            new Date(),
            parseISO(step.actual_start_time)
          );
          // Total elapsed = pre-existing elapsed (e.g. seeded by U3 cascading
          // time, or accumulated across pause/resume) + the live tick. The
          // backend's ``Step.start()`` resets actual_start_time to "now" on
          // every resume but preserves elapsed_seconds across pauses, so this
          // formula stays correct under pause/resume.
          const elapsedSoFar = (step.elapsed_seconds || 0) + elapsedSinceStart;
          const secondsRemaining = step.duration_seconds - elapsedSoFar;
          const fired = step.prewarnings_fired || [];

          step.prewarning_offsets_seconds.forEach((offset) => {
            if (fired.includes(offset)) return;
            const localKey = `${step.id}:${offset}`;
            if (localPrewarningEmits.current.has(localKey)) return;
            if (secondsRemaining <= offset) {
              localPrewarningEmits.current.add(localKey);
              socketService.emitPrewarningHit(step.id, offset);
            }
          });
        }
      });
    }, 1000);

    return () => clearInterval(timer);
  }, []);

  // Handle step actions
  const handleStepStart = async (stepId: string) => {
    if (!experiment) return;

    // U6: conflict detection now lives on the server. The client-side
    // pairwise check that used to live here was removed -- it duplicated
    // the backend's `Scheduler.check_for_conflicts` (run once per
    // `experiment_update`), and when both fired the user saw a redundant
    // dialog. Conflicts are surfaced via the warning Alert above the step
    // grid; nothing to do here except start the step.
    try {
      const updatedExperiment = await apiClient.startStep(stepId);
      setExperiment(updatedExperiment);

      // Set this step as active
      const newActiveIndex = updatedExperiment.steps.findIndex(step => step.id === stepId);
      if (newActiveIndex !== -1) {
        setActiveStepIndex(newActiveIndex);
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

  // ``handleStepComplete`` lives near the top of the component as a stable
  // useCallback so the per-second tick effect can reference it without
  // re-creating the interval. See the comment block above the timer effect.

  const handleStepSkip = async (stepId: string) => {
    if (!experiment) return;

    // Server-sourced state: POST /api/steps/<id>/skip and let the resulting
    // ``experiment_update`` socket push (or the HTTP response) update local
    // state. Don't optimistically mutate ``experiment`` here -- doing that
    // is what lets two tabs of the same experiment drift, and what made the
    // pre-U5 client think a step was SKIPPED while the server still had it
    // RUNNING.
    try {
      const updatedExperiment = await apiClient.skipStep(stepId);
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
    const safe = Math.max(0, Math.floor(seconds));
    const mins = Math.floor(safe / 60);
    const secs = safe % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  // Convert duration_seconds -> human-readable minutes for the static labels.
  // Sub-minute durations show "<1 min" so a 30-second step doesn't render as
  // "0 min" (the audit's // 60 truncation bug, surfaced visually).
  const formatDurationMinutes = (seconds: number): string => {
    if (!Number.isFinite(seconds) || seconds <= 0) return '0 min';
    if (seconds < 60) return '<1 min';
    return `${Math.floor(seconds / 60)} min`;
  };

  const getProgress = (step: Step) => {
    if (!step.elapsed_seconds || step.step_type === StepType.TASK) return 0;
    if (!step.duration_seconds || step.duration_seconds <= 0) return 0;
    const progress = (step.elapsed_seconds / step.duration_seconds) * 100;
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
                      Type: {activeStep.step_type.replace('_', ' ')}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" gutterBottom>
                      Duration: {formatDurationMinutes(activeStep.duration_seconds)}
                    </Typography>
                    {activeStep.resource_required && (
                      <Typography variant="body2" color="text.secondary" gutterBottom>
                        Resource: {activeStep.resource_required}
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
                            {formatTime(activeStep.elapsed_seconds)}
                          </Typography>
                        </Box>

                        {activeStep.step_type !== StepType.TASK && (
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
                    {activeStep.step_type === StepType.TASK && (
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
        
        {/* Resource conflict warnings (U6). Non-blocking on purpose: the
            previous dialog interrupted the user's flow on every Start click.
            The server's check_for_conflicts powers this list, so it stays
            consistent with whatever U7 will use to fire notifications. */}
        {conflicts.length > 0 && (
          <Alert severity="warning" sx={{ mb: 3 }}>
            <Typography variant="subtitle2" gutterBottom>
              Resource conflicts detected ({conflicts.length}):
            </Typography>
            {conflicts.map((c) => (
              <Typography key={`${c.step_a}-${c.step_b}-${c.resource}`} variant="body2">
                {c.step_a_name} ({c.condition_a_name}) ↔ {c.step_b_name} ({c.condition_b_name}) on {c.resource} ({c.overlap_seconds}s overlap)
              </Typography>
            ))}
          </Alert>
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
                          {formatTime(step.elapsed_seconds)}
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
                    secondary={`Type: ${step.step_type.replace('_', ' ')} | Duration: ${formatDurationMinutes(step.duration_seconds)} | Resource: ${step.resource_required || 'none'}`}
                  />
                </ListItem>
              </React.Fragment>
            ))}
          </List>
        </Box>
      </Box>
      
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
                <strong>Type:</strong> {selectedStep.step_type.replace('_', ' ')}
              </Typography>
              <Typography variant="body2" gutterBottom>
                <strong>Duration:</strong> {formatDurationMinutes(selectedStep.duration_seconds)}
              </Typography>
              <Typography variant="body2" gutterBottom>
                <strong>Status:</strong> {selectedStep.status}
              </Typography>
              {selectedStep.resource_required && (
                <Typography variant="body2" gutterBottom>
                  <strong>Resource Needed:</strong> {selectedStep.resource_required}
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
                <strong>Scheduled Start:</strong> {formatDateTime(selectedStep.scheduled_start_time)}
              </Typography>
              <Typography variant="body2" gutterBottom>
                <strong>Actual Start:</strong> {formatDateTime(selectedStep.actual_start_time)}
              </Typography>
              {selectedStep.actual_end_time && (
                <Typography variant="body2" gutterBottom>
                  <strong>Actual End:</strong> {formatDateTime(selectedStep.actual_end_time)}
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