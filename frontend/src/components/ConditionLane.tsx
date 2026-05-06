import React from 'react';
import {
  Alert,
  Box,
  Button,
  ButtonGroup,
  Card,
  CardActions,
  CardContent,
  Chip,
  LinearProgress,
  Paper,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material';
import { alpha } from '@mui/material/styles';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import PauseIcon from '@mui/icons-material/Pause';
import CheckIcon from '@mui/icons-material/Check';
import SkipNextIcon from '@mui/icons-material/SkipNext';
import TimerIcon from '@mui/icons-material/Timer';
import ErrorIcon from '@mui/icons-material/Error';
import { format, parseISO } from 'date-fns';
import { Condition, Step } from '../api/client';
import { getPaletteColor } from './ConditionPaletteSwatch';

// Local mirrors of the backend enum values. We deliberately don't import these
// from a shared module so the component stays self-contained for U7's focus
// mode (which renders ConditionLane as its sole child). Keep in sync with the
// equivalent maps in ExperimentRunner.tsx.
export const StepStatus = {
  PENDING: 'pending',
  READY: 'ready',
  RUNNING: 'running',
  PAUSED: 'paused',
  COMPLETED: 'completed',
  SKIPPED: 'skipped',
  ERROR: 'error',
} as const;

export const StepType = {
  FIXED_DURATION: 'fixed_duration',
  TASK: 'task',
  FIXED_START: 'fixed_start',
  AUTOMATED_TASK: 'automated_task',
} as const;

// ---------------------------------------------------------------------------
// Lane background color choice (U6).
//
// The U2 audit-finding called out that `PALETTE_COLORS[key].bg` is a saturated
// mid-tone meant for chips and the Designer's lane-header strip -- not for the
// full-row body fill of a Runner swimlane (it'd be visually overwhelming and
// kill the contrast of the step Cards inside). Two options were on the table:
//
//   A. Extend the palette object with a `bgSoft` field per entry.
//   B. Derive a softer shade from the existing `bg` via `alpha()` at runtime.
//
// We pick (B). Reasoning:
//
//   * The palette object is shared with ConditionPaletteSwatch and
//     ConditionEditor (color picker). Adding `bgSoft` means touching every
//     consumer's TS contract for a value only the Runner uses today.
//   * The MUI `alpha(color, 0.08)` helper is already a project-blessed tool
//     for this -- the Designer uses the saturated `bg` directly on its lane
//     headers, and the Runner using `alpha(bg, 0.08)` keeps the visual
//     relationship "header is the saturated color, body is a tinted wash"
//     totally derivable instead of needing a hand-tuned second value.
//   * If a future design need calls for a hand-picked soft tone (e.g., to
//     fix a specific palette entry that doesn't desaturate well), upgrading
//     to (A) is a strictly additive change.
//
// 0.08 is the visual sweet spot: enough tint that the lane reads as "this
// belongs to Condition X", little enough that the white step Cards inside
// stay legible without extra elevation.
const LANE_BG_ALPHA = 0.08;

// Status -> Chip props. Mirrors ExperimentRunner.getStepStatusChip so the
// per-step rendering inside the lane stays consistent with the active-step
// card outside (and the all-steps list, eventually replaced by this).
const renderStatusChip = (status: string): JSX.Element => {
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

const formatTime = (seconds?: number): string => {
  if (seconds === undefined) return '--:--';
  const safe = Math.max(0, Math.floor(seconds));
  const mins = Math.floor(safe / 60);
  const secs = safe % 60;
  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
};

const formatDurationMinutes = (seconds: number): string => {
  if (!Number.isFinite(seconds) || seconds <= 0) return '0 min';
  if (seconds < 60) return '<1 min';
  return `${Math.floor(seconds / 60)} min`;
};

const formatScheduled = (iso?: string): string => {
  if (!iso) return '';
  try {
    return format(parseISO(iso), 'HH:mm');
  } catch {
    return '';
  }
};

const getProgress = (step: Step): number => {
  if (!step.elapsed_seconds || step.step_type === StepType.TASK) return 0;
  if (!step.duration_seconds || step.duration_seconds <= 0) return 0;
  return Math.min((step.elapsed_seconds / step.duration_seconds) * 100, 100);
};

// Per-step action handlers. The Runner owns the API round-trip; the lane
// just emits intent through these callbacks. All optional so a read-only
// rendering (e.g., a future WatchView reuse) can pass none of them.
export interface ConditionLaneStepActions {
  onStartStep?: (step: Step) => void;
  onPauseStep?: (step: Step) => void;
  onResumeStep?: (step: Step) => void;
  onCompleteStep?: (step: Step) => void;
  onSkipStep?: (step: Step) => void;
  onExtendStep?: (step: Step, deltaSeconds: number) => void;
}

export interface ConditionLaneProps extends ConditionLaneStepActions {
  // The condition this lane represents. Drives header label + lane background.
  condition: Condition;
  // The steps belonging to this condition. The caller (typically
  // ExperimentRunner) is responsible for filtering experiment.steps by
  // condition_id before passing them in -- the lane never re-resolves.
  steps: Step[];
  // ID of the step currently considered "active" by the Runner (the step
  // whose action buttons should be visible, the step that gets the elevated
  // card style). Pass null when no step is active (e.g., everything completed).
  activeStepId: string | null;
  // When provided, the lane header renders "Push +5m / -5m" buttons that
  // invoke this callback. When omitted (e.g., U7 focus mode may pass none),
  // the controls are hidden so a read-only view can reuse the same component.
  onPushCondition?: (deltaSeconds: number) => void;
  // Click handler for non-active step cards (typically opens a step-details
  // dialog in the Runner). Active steps render their full action buttons in
  // place and ignore this.
  onStepClick?: (step: Step) => void;
  // Layout variant. "swimlane" (default) is a horizontal row of compact
  // step cards used by the Runner's main grid. "focus" is U7's tablet-mode
  // single-condition view, where one big card per step makes sense. For U6
  // the "focus" variant uses the same per-step card render as "swimlane"
  // but stacks vertically with bigger spacing -- U7 will refine the active
  // card into the full-screen big-button layout when it lands.
  variant?: 'swimlane' | 'focus';
}

// Per-step card. Active steps get the full action button row; non-active
// steps render compact + clickable.
const StepCard: React.FC<{
  step: Step;
  isActive: boolean;
  variant: 'swimlane' | 'focus';
  laneAccentColor: string;
  actions: ConditionLaneStepActions;
  onStepClick?: (step: Step) => void;
}> = ({ step, isActive, variant, laneAccentColor, actions, onStepClick }) => {
  const status = step.status;
  const showStartButton = status === StepStatus.READY;
  const showPauseButton =
    status === StepStatus.RUNNING && step.step_type === StepType.TASK;
  const showCompleteButton =
    status === StepStatus.RUNNING || status === StepStatus.PAUSED;
  const showResumeButton = status === StepStatus.PAUSED;
  const showSkipButton =
    status !== StepStatus.COMPLETED && status !== StepStatus.SKIPPED;
  const showLiveEdit =
    isActive &&
    status !== StepStatus.COMPLETED &&
    status !== StepStatus.SKIPPED;

  const cardSx = isActive
    ? {
        // Highlight the active step with a left accent strip in the lane's
        // color + slightly elevated shadow. The accent color comes from the
        // lane (saturated palette bg) so the operator can spot the active
        // step even when scanning past chip colors that read similarly on
        // small screens.
        borderLeft: `4px solid ${laneAccentColor}`,
        boxShadow: 3,
      }
    : {
        // Non-active steps: compact, clickable, ghosty. Hover lifts so the
        // affordance is obvious.
        cursor: onStepClick ? 'pointer' : 'default',
        opacity: status === StepStatus.COMPLETED || status === StepStatus.SKIPPED ? 0.7 : 1,
        '&:hover': onStepClick ? { boxShadow: 2 } : undefined,
      };

  const handleCardClick = () => {
    if (!isActive && onStepClick) onStepClick(step);
  };

  return (
    <Card
      sx={{
        ...cardSx,
        // In "focus" variant we let the card take the full lane width; in
        // "swimlane" we cap at a comfortable card size so a long lane stays
        // scannable as a row.
        minWidth: variant === 'focus' ? '100%' : 220,
        flex: variant === 'focus' ? '1 1 auto' : '0 0 auto',
      }}
      onClick={handleCardClick}
    >
      <CardContent sx={{ pb: 1 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1, gap: 1 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: isActive ? 600 : 500 }}>
            {step.name}
          </Typography>
          {renderStatusChip(status)}
        </Box>
        <Typography variant="body2" color="text.secondary">
          {formatDurationMinutes(step.duration_seconds)}
          {step.resource_required ? ` | ${step.resource_required}` : ''}
        </Typography>
        {step.scheduled_start_time && (
          <Typography variant="caption" color="text.secondary" display="block">
            Scheduled: {formatScheduled(step.scheduled_start_time)}
            {step.scheduled_end_time ? ` - ${formatScheduled(step.scheduled_end_time)}` : ''}
          </Typography>
        )}
        {status === StepStatus.RUNNING && (
          <Box sx={{ mt: 1 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', mb: 0.5 }}>
              <TimerIcon fontSize="small" sx={{ mr: 0.5 }} />
              <Typography variant="body2" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                {formatTime(step.elapsed_seconds)}
              </Typography>
            </Box>
            {step.step_type !== StepType.TASK && (
              <LinearProgress
                variant="determinate"
                value={getProgress(step)}
                sx={{ height: 6, borderRadius: 1 }}
              />
            )}
          </Box>
        )}
      </CardContent>
      {isActive && (
        <CardActions sx={{ flexWrap: 'wrap', gap: 1 }}>
          {showStartButton && actions.onStartStep && (
            <Button
              color="primary"
              variant="contained"
              size="small"
              startIcon={<PlayArrowIcon />}
              onClick={() => actions.onStartStep!(step)}
            >
              Start
            </Button>
          )}
          {showPauseButton && actions.onPauseStep && (
            <Button
              color="warning"
              variant="contained"
              size="small"
              startIcon={<PauseIcon />}
              onClick={() => actions.onPauseStep!(step)}
            >
              Pause
            </Button>
          )}
          {showResumeButton && actions.onResumeStep && (
            <Button
              color="primary"
              variant="contained"
              size="small"
              startIcon={<PlayArrowIcon />}
              onClick={() => actions.onResumeStep!(step)}
            >
              Resume
            </Button>
          )}
          {showCompleteButton && actions.onCompleteStep && (
            <Button
              color="success"
              variant="contained"
              size="small"
              startIcon={<CheckIcon />}
              onClick={() => actions.onCompleteStep!(step)}
            >
              Complete
            </Button>
          )}
          {showSkipButton && actions.onSkipStep && (
            <Button
              color="error"
              size="small"
              startIcon={<SkipNextIcon />}
              onClick={() => actions.onSkipStep!(step)}
            >
              Skip
            </Button>
          )}
          {showLiveEdit && actions.onExtendStep && (
            <ButtonGroup
              size="small"
              variant="outlined"
              sx={{ ml: 'auto' }}
              aria-label="adjust step duration"
            >
              <Button
                onClick={() => actions.onExtendStep!(step, -60)}
                aria-label="shrink one minute"
              >
                -1m
              </Button>
              <Button
                onClick={() => actions.onExtendStep!(step, 60)}
                aria-label="extend one minute"
              >
                +1m
              </Button>
              <Button
                onClick={() => actions.onExtendStep!(step, -300)}
                aria-label="shrink five minutes"
              >
                -5m
              </Button>
              <Button
                onClick={() => actions.onExtendStep!(step, 300)}
                aria-label="extend five minutes"
              >
                +5m
              </Button>
            </ButtonGroup>
          )}
        </CardActions>
      )}
    </Card>
  );
};

const ConditionLane: React.FC<ConditionLaneProps> = ({
  condition,
  steps,
  activeStepId,
  onPushCondition,
  onStepClick,
  variant = 'swimlane',
  onStartStep,
  onPauseStep,
  onResumeStep,
  onCompleteStep,
  onSkipStep,
  onExtendStep,
}) => {
  const palette = getPaletteColor(condition.color);
  // Lane body wash: derived from the saturated palette bg via alpha() at
  // runtime (see LANE_BG_ALPHA comment block). The lane header retains the
  // full saturated bg so the contract "header chip color = condition color"
  // holds across Designer + Runner.
  const laneBg = alpha(palette.bg, LANE_BG_ALPHA);

  const stepActions: ConditionLaneStepActions = {
    onStartStep,
    onPauseStep,
    onResumeStep,
    onCompleteStep,
    onSkipStep,
    onExtendStep,
  };

  const headerControls = onPushCondition && (
    <ButtonGroup
      size="small"
      variant="outlined"
      // Header is rendered on top of the saturated palette color; outlined
      // buttons need a contrasting border + text so they remain legible
      // against bright backgrounds (coral / amber / gold). We force the
      // foreground to the palette's chosen `fg` token (already validated for
      // WCAG AA against `bg`) and make the border match.
      sx={{
        ml: 'auto',
        '& .MuiButton-root': {
          color: palette.fg,
          borderColor: alpha(palette.fg, 0.5),
          '&:hover': {
            borderColor: palette.fg,
            backgroundColor: alpha(palette.fg, 0.12),
          },
        },
      }}
      aria-label={`shift ${condition.name} schedule`}
    >
      <Tooltip title={`Push "${condition.name}" upcoming steps back 5 min`}>
        <Button
          onClick={() => onPushCondition(-300)}
          aria-label={`push ${condition.name} earlier 5 minutes`}
        >
          -5m
        </Button>
      </Tooltip>
      <Tooltip title={`Push "${condition.name}" upcoming steps forward 5 min`}>
        <Button
          onClick={() => onPushCondition(300)}
          aria-label={`push ${condition.name} later 5 minutes`}
        >
          +5m
        </Button>
      </Tooltip>
    </ButtonGroup>
  );

  return (
    <Paper
      // Outer Paper holds the lane background wash. We rely on the body's
      // own elevated cards to provide contrast against this tint.
      sx={{ overflow: 'hidden', bgcolor: laneBg }}
      aria-label={`${condition.name} lane`}
    >
      {/* Lane header. Saturated palette color, condition name + soft step
          count chip, optional push controls aligned to the right. */}
      <Box
        sx={{
          bgcolor: palette.bg,
          color: palette.fg,
          px: 2,
          py: 1,
          display: 'flex',
          alignItems: 'center',
          gap: 1,
        }}
      >
        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
          {condition.name || '(unnamed)'}
        </Typography>
        <Typography variant="caption" sx={{ opacity: 0.85 }}>
          ({steps.length} step{steps.length === 1 ? '' : 's'})
        </Typography>
        {headerControls}
      </Box>
      {/* Lane body. Empty state is explicit so the user can tell a Condition
          exists even when it has zero steps (e.g., mid-design between the
          Conditions sidebar add and the first Step assignment). */}
      <Box sx={{ px: 2, py: 2 }}>
        {steps.length === 0 ? (
          <Alert severity="info" variant="outlined">
            No steps in this Condition.
          </Alert>
        ) : (
          <Stack
            direction={variant === 'swimlane' ? 'row' : 'column'}
            spacing={2}
            useFlexGap
            flexWrap="wrap"
          >
            {steps.map((step) => (
              <StepCard
                key={step.id}
                step={step}
                isActive={step.id === activeStepId}
                variant={variant}
                laneAccentColor={palette.bg}
                actions={stepActions}
                onStepClick={onStepClick}
              />
            ))}
          </Stack>
        )}
      </Box>
    </Paper>
  );
};

export default ConditionLane;
