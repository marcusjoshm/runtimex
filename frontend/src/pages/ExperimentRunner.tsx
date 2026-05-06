import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Box,
  Button,
  Container,
  Grid,
  LinearProgress,
  Paper,
  Stack,
  Typography,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  IconButton,
  Alert,
  Snackbar,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { format, differenceInSeconds, parseISO } from 'date-fns';
import apiClient, { Experiment, Step, Condition, Conflict } from '../api/client';
import socketService from '../api/socket';
import ConditionLane from '../components/ConditionLane';

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
  // U5 live-edit feedback. Both the server's clamp warning and any error
  // from the extend round-trip surface here. We keep the message and
  // severity together so the Snackbar can render the right color without a
  // second piece of state. ``null`` => not visible.
  const [liveEditFeedback, setLiveEditFeedback] = useState<{
    message: string;
    severity: 'success' | 'warning' | 'error';
  } | null>(null);

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

  // U5: extend / shrink the active step by a fixed delta (seconds). On 200,
  // we let the socket's ``experiment_update`` push handle local-state
  // refresh -- mirrors the existing skip/start/pause/complete pattern that
  // already lives in this file. The Promise's resolved payload still gets
  // applied directly so the buttons feel snappy without waiting for the
  // socket round-trip; both sources converge on the same shape.
  //
  // Negative deltas may trigger the server's shrink-clamp; the response
  // includes a ``warning`` string in that case and we surface it in the
  // Snackbar. Errors (network / 403 / 404) also land in the Snackbar with
  // ``severity: 'error'`` so the operator gets a non-blocking signal
  // without an alert() dialog interrupting the bench flow.
  const handleExtendStep = async (stepId: string, deltaSeconds: number) => {
    try {
      const response = await apiClient.extendStep(stepId, deltaSeconds);
      setExperiment(response);
      if (response.warning) {
        setLiveEditFeedback({ message: response.warning, severity: 'warning' });
      } else {
        const sign = deltaSeconds >= 0 ? '+' : '-';
        const minutes = Math.abs(deltaSeconds) / 60;
        const label = minutes >= 1
          ? `${sign}${minutes} min`
          : `${sign}${Math.abs(deltaSeconds)} sec`;
        setLiveEditFeedback({
          message: `Step duration adjusted (${label})`,
          severity: 'success',
        });
      }
    } catch (err: any) {
      console.error('Failed to extend step:', err);
      const status = err?.response?.status;
      const detail =
        err?.response?.data?.error ||
        (status === 403 ? 'Edit permission required'
         : status === 404 ? 'Step not found'
         : 'Failed to adjust step duration');
      setLiveEditFeedback({ message: detail, severity: 'error' });
    }
  };

  const showStepDetails = (stepId: string) => {
    setSelectedStepId(stepId);
    setShowInfoDialog(true);
  };

  // U5 push-condition handler. Centralised here so each lane's "Push" buttons
  // share the same error / Snackbar plumbing as handleExtendStep above. The
  // server applies the delta to PENDING/READY steps in the named Condition,
  // re-runs conflict detection, and broadcasts ``experiment_update``; the
  // socket handler refreshes our local state independently.
  const handlePushCondition = useCallback(
    async (conditionId: string, conditionName: string, deltaSeconds: number) => {
      try {
        const response = await apiClient.pushCondition(conditionId, deltaSeconds);
        setExperiment(response);
        const sign = deltaSeconds >= 0 ? '+' : '-';
        const minutes = Math.abs(deltaSeconds) / 60;
        const label =
          minutes >= 1 ? `${sign}${minutes} min` : `${sign}${Math.abs(deltaSeconds)} sec`;
        setLiveEditFeedback({
          message: `Pushed "${conditionName}" by ${label}`,
          severity: 'success',
        });
      } catch (err: any) {
        console.error('Failed to push condition:', err);
        const status = err?.response?.status;
        const detail =
          err?.response?.data?.error ||
          (status === 403
            ? 'Edit permission required'
            : status === 404
            ? 'Condition not found'
            : 'Failed to push condition');
        setLiveEditFeedback({ message: detail, severity: 'error' });
      }
    },
    []
  );

  // Convert duration_seconds -> human-readable minutes for the static labels.
  // Sub-minute durations show "<1 min" so a 30-second step doesn't render as
  // "0 min" (the audit's // 60 truncation bug, surfaced visually).
  const formatDurationMinutes = (seconds: number): string => {
    if (!Number.isFinite(seconds) || seconds <= 0) return '0 min';
    if (seconds < 60) return '<1 min';
    return `${Math.floor(seconds / 60)} min`;
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
  const activeStepId = activeStep?.id ?? null;
  const pendingSteps = experiment.steps.filter(step => step.status === StepStatus.PENDING);
  const readySteps = experiment.steps.filter(step => step.status === StepStatus.READY);
  const runningSteps = experiment.steps.filter(step => step.status === StepStatus.RUNNING);
  const completedSteps = experiment.steps.filter(step => step.status === StepStatus.COMPLETED);
  const selectedStep = selectedStepId ? experiment.steps.find(step => step.id === selectedStepId) : null;

  const allStepsComplete = experiment.steps.every(step =>
    step.status === StepStatus.COMPLETED || step.status === StepStatus.SKIPPED);

  // Group steps by Condition for the swimlane layout. We sort lanes by
  // ``order_index`` so the visual order matches what the Designer's
  // Conditions sidebar showed at save time. Within each lane we preserve the
  // experiment.steps array order (the user's authored sequence).
  //
  // Why inline rather than lift to a shared util: the Designer's grouping
  // carries an ``originalIndex`` per entry (so move/delete handlers stay O(1))
  // -- a contract the Runner doesn't need. Lifting a single util would force
  // either a wider type or two near-identical groupers; the inline 5-line
  // map+filter pays its weight here. See the Designer's ``stepsByCondition``
  // (ExperimentDesigner.tsx) for the shape if/when this needs unifying.
  const conditions: Condition[] = (experiment.conditions ?? [])
    .slice()
    .sort((a, b) => a.order_index - b.order_index);
  // Defensive fallback: if the experiment payload predates U1 (shouldn't
  // happen post-backfill, but a stale mock could) we render a single
  // synthetic "Main" lane so the page doesn't go blank.
  const lanes: Array<{ condition: Condition; steps: Step[] }> =
    conditions.length > 0
      ? conditions.map((c) => ({
          condition: c,
          steps: experiment.steps.filter((s) => s.condition_id === c.id),
        }))
      : [
          {
            condition: {
              id: 'synthetic-main',
              experiment_id: experiment.id,
              name: 'Main',
              color: 'slate',
              order_index: 0,
            },
            steps: experiment.steps,
          },
        ];

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
        
        {/* Resource conflict warnings (U6). Non-blocking on purpose: the
            previous dialog interrupted the user's flow on every Start click.
            The server's check_for_conflicts powers this list (with U2's
            condition labels), so it stays consistent with whatever U7 will
            use to fire notifications. Rendered above the swimlanes so a
            multi-lane experiment shows the cross-lane impact at a glance. */}
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

        {/* U6 swimlane layout. One ConditionLane per Condition, sorted by
            order_index. Each lane handles its own per-step rendering,
            highlights the active step, surfaces start/pause/complete/skip
            controls on it, and (when ``onPushCondition`` is provided) shows
            the +/-5m push controls in its header. The ``onStepClick`` for
            non-active step cards opens the existing details dialog so the
            page's information density isn't lost on a single-active-step
            view. */}
        <Stack spacing={3} sx={{ mb: 4 }}>
          {lanes.map(({ condition, steps }) => (
            <ConditionLane
              key={condition.id}
              condition={condition}
              steps={steps}
              activeStepId={activeStepId}
              onStepClick={(s) => showStepDetails(s.id)}
              onStartStep={(s) => handleStepStart(s.id)}
              onPauseStep={(s) => handleStepPause(s.id)}
              onResumeStep={(s) => handleStepResume(s.id)}
              onCompleteStep={(s) => handleStepComplete(s.id)}
              onSkipStep={(s) => handleStepSkip(s.id)}
              onExtendStep={(s, delta) => handleExtendStep(s.id, delta)}
              onPushCondition={
                // Only attach the push handler for "real" conditions; the
                // synthetic-main fallback above can't push anything (the
                // server has no Condition row with that id and would 404).
                condition.id === 'synthetic-main'
                  ? undefined
                  : (delta) =>
                      handlePushCondition(condition.id, condition.name, delta)
              }
            />
          ))}
        </Stack>
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

      {/* U5 live-edit feedback. The Snackbar is non-blocking on purpose --
          extend/shrink is a high-frequency operation at the bench, and a
          modal alert would interrupt the operator's flow on every tap. The
          severity comes from handleExtendStep: 'warning' for the
          shrink-clamp message, 'error' for HTTP failures, 'success' for
          plain extend confirmation. */}
      <Snackbar
        open={liveEditFeedback !== null}
        autoHideDuration={4000}
        onClose={() => setLiveEditFeedback(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        {liveEditFeedback ? (
          <Alert
            onClose={() => setLiveEditFeedback(null)}
            severity={liveEditFeedback.severity}
            variant="filled"
            sx={{ width: '100%' }}
          >
            {liveEditFeedback.message}
          </Alert>
        ) : undefined}
      </Snackbar>
    </Container>
  );
};

export default ExperimentRunner; 