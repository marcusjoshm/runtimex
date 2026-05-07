import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Box,
  Chip,
  IconButton,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material';
import { alpha } from '@mui/material/styles';
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft';
import ChevronRightIcon from '@mui/icons-material/ChevronRight';
import { Condition, Experiment, Step } from '../api/client';
import ConditionLane from './ConditionLane';
import { getPaletteColor } from './ConditionPaletteSwatch';

/**
 * U7 tablet focus mode.
 *
 * Renders ONE Condition at a time so a single operator at the bench can
 * watch the active step on a phone or tablet without losing the touch
 * targets to a multi-lane swimlane. Driven by the same Experiment +
 * socket data the swimlane Runner uses; this is purely a presentational
 * shell on top of the existing state.
 *
 * Component composition (chosen over duplicating ConditionLane):
 *
 *   FocusModeRunner
 *     |- internal navigator strip (chevrons + "Condition X / N" + push)
 *     |- ConditionLane variant="focus" hideHeader hideNonActiveSteps
 *
 * The chevron + condition-name navigator was originally proposed as a
 * separate ``FocusModeNavigator`` component; we kept it inline because
 * it's three rendered elements that pull from the same local state
 * (``currentConditionIndex``) and have no other consumer. Lifting it into
 * its own file would force the index state up here and pass it back
 * down -- twice the wiring for zero reuse.
 */

// Native pointer-event swipe configuration. We deliberately avoid a new
// dependency (react-swipeable was the documented fallback in the plan; not
// needed). 50 pixels of horizontal travel with vertical drift below the
// horizontal-drift threshold counts as a swipe. Anything shorter or
// vertical-dominant is ignored so a downward scroll doesn't accidentally
// flip Conditions on a small viewport.
const SWIPE_THRESHOLD_PX = 50;
const VERTICAL_TOLERANCE_PX = 60;

export interface FocusModeRunnerProps {
  experiment: Experiment;
  // ID of the step currently considered active by the parent Runner. This
  // shape mirrors ConditionLaneProps.activeStepId so all three layers
  // (page -> focus shell -> lane) agree on which step's controls render.
  activeStepId: string | null;
  // Step lifecycle callbacks. Pass-through to ConditionLane; FocusModeRunner
  // never calls the API itself. Optional so a future read-only embed can
  // omit them.
  onStartStep?: (step: Step) => void;
  onPauseStep?: (step: Step) => void;
  onResumeStep?: (step: Step) => void;
  onCompleteStep?: (step: Step) => void;
  onSkipStep?: (step: Step) => void;
  onExtendStep?: (step: Step, deltaSeconds: number) => void;
  // Push the visible Condition's PENDING/READY steps by N seconds. Same
  // signature as the swimlane's push handler so the parent Runner can
  // share its handlePushCondition implementation between layouts.
  onPushCondition?: (
    conditionId: string,
    conditionName: string,
    deltaSeconds: number
  ) => void;
}

const FocusModeRunner: React.FC<FocusModeRunnerProps> = ({
  experiment,
  activeStepId,
  onStartStep,
  onPauseStep,
  onResumeStep,
  onCompleteStep,
  onSkipStep,
  onExtendStep,
  onPushCondition,
}) => {
  // Order-by-order_index, matching the swimlane Runner's grouping. Using
  // useMemo keeps the array reference stable across re-renders so the
  // dependency arrays below don't churn.
  const conditions: Condition[] = useMemo(
    () =>
      (experiment.conditions ?? [])
        .slice()
        .sort((a, b) => a.order_index - b.order_index),
    [experiment.conditions]
  );

  // Defensive synthetic fallback. This mirrors ExperimentRunner's "if no
  // conditions came back from the server, render a Main lane" branch so
  // the focus view never goes blank for legacy data.
  const lanes = useMemo(() => {
    if (conditions.length > 0) {
      return conditions.map((c) => ({
        condition: c,
        steps: experiment.steps.filter((s) => s.condition_id === c.id),
      }));
    }
    return [
      {
        condition: {
          id: 'synthetic-main',
          experiment_id: experiment.id,
          name: 'Main',
          color: 'slate',
          order_index: 0,
        } as Condition,
        steps: experiment.steps,
      },
    ];
  }, [conditions, experiment.id, experiment.steps]);

  // Visible Condition index. We auto-advance to the lane that owns the
  // active step on first mount + whenever the active step changes -- the
  // operator's "current focus" should track the running step, not where
  // they happened to swipe last. Manual swipes / chevron clicks override
  // until the next active-step change.
  const [currentConditionIndex, setCurrentConditionIndex] = useState(0);
  const lastAutoFollowedStepId = useRef<string | null>(null);

  useEffect(() => {
    if (!activeStepId || activeStepId === lastAutoFollowedStepId.current) return;
    const idx = lanes.findIndex((l) =>
      l.steps.some((s) => s.id === activeStepId)
    );
    if (idx >= 0) {
      setCurrentConditionIndex(idx);
      lastAutoFollowedStepId.current = activeStepId;
    }
  }, [activeStepId, lanes]);

  // Clamp the visible index whenever the lane count shrinks (e.g., a
  // condition is deleted in another tab). Prevents an out-of-bounds undef.
  useEffect(() => {
    if (currentConditionIndex >= lanes.length) {
      setCurrentConditionIndex(Math.max(0, lanes.length - 1));
    }
  }, [currentConditionIndex, lanes.length]);

  const goPrev = () =>
    setCurrentConditionIndex((i) => (i > 0 ? i - 1 : i));
  const goNext = () =>
    setCurrentConditionIndex((i) => (i < lanes.length - 1 ? i + 1 : i));

  // Native pointer-event swipe. We track only x at start; on end we
  // measure deltas and only fire if the gesture is horizontal-dominant.
  // ``touch-action: pan-y`` on the container keeps vertical scroll for
  // any overflow content (the big countdown card itself shouldn't scroll,
  // but nested content like a long condition description might).
  const swipeStart = useRef<{ x: number; y: number } | null>(null);

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    swipeStart.current = { x: e.clientX, y: e.clientY };
  };

  const handlePointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    const start = swipeStart.current;
    swipeStart.current = null;
    if (!start) return;
    const dx = e.clientX - start.x;
    const dy = e.clientY - start.y;
    if (Math.abs(dy) > VERTICAL_TOLERANCE_PX) return; // mostly vertical -> ignore
    if (Math.abs(dx) < SWIPE_THRESHOLD_PX) return; // too small -> ignore
    if (dx < 0) goNext(); // left swipe = next
    else goPrev(); // right swipe = prev
  };

  const handlePointerCancel = () => {
    swipeStart.current = null;
  };

  // Empty experiment guard. The plan calls for a no-op but legible state.
  if (lanes.length === 0) {
    return (
      <Box sx={{ p: 4, textAlign: 'center' }}>
        <Typography variant="h5">No conditions to display.</Typography>
      </Box>
    );
  }

  const currentLane = lanes[currentConditionIndex] ?? lanes[0];
  const palette = getPaletteColor(currentLane.condition.color);

  return (
    <Box
      // Wrap the whole focus view in a swipeable region. ``touch-action:
      // pan-y`` keeps native vertical scroll alive even though we steal
      // horizontal gestures. ``user-select: none`` stops a long-press +
      // drag from selecting the big countdown text instead of swiping.
      onPointerDown={handlePointerDown}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerCancel}
      sx={{
        touchAction: 'pan-y',
        userSelect: 'none',
        display: 'flex',
        flexDirection: 'column',
        gap: 2,
        // The page-level ExperimentRunner already wraps us in a Container,
        // so we only need to fill that horizontal slot. Vertical: we want
        // the active card to dominate the viewport, so flex-grow inside
        // the card carries the rest of the height.
        minHeight: '70vh',
      }}
      aria-label="focus mode condition view"
    >
      {/* Inline navigator. Chevrons left/right + condition name + step
          count + condition-color chip + push controls. The header strip
          paints in the condition's saturated palette color so the visual
          mapping stays consistent with the swimlane. */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1.5,
          bgcolor: palette.bg,
          color: palette.fg,
          px: 2,
          py: 1.5,
          borderRadius: 1,
        }}
      >
        <Tooltip title="Previous condition">
          <span>
            <IconButton
              onClick={goPrev}
              disabled={currentConditionIndex === 0}
              size="large"
              sx={{ color: palette.fg, '&.Mui-disabled': { color: alpha(palette.fg, 0.4) } }}
              aria-label="previous condition"
            >
              <ChevronLeftIcon fontSize="large" />
            </IconButton>
          </span>
        </Tooltip>
        <Box sx={{ flexGrow: 1, textAlign: 'center' }}>
          <Typography variant="h6" sx={{ fontWeight: 700, lineHeight: 1.2 }}>
            {currentLane.condition.name || '(unnamed)'}
          </Typography>
          <Typography variant="caption" sx={{ opacity: 0.9 }}>
            Condition {currentConditionIndex + 1} of {lanes.length}
            {' | '}
            {currentLane.steps.length} step
            {currentLane.steps.length === 1 ? '' : 's'}
          </Typography>
        </Box>
        <Tooltip title="Next condition">
          <span>
            <IconButton
              onClick={goNext}
              disabled={currentConditionIndex >= lanes.length - 1}
              size="large"
              sx={{ color: palette.fg, '&.Mui-disabled': { color: alpha(palette.fg, 0.4) } }}
              aria-label="next condition"
            >
              <ChevronRightIcon fontSize="large" />
            </IconButton>
          </span>
        </Tooltip>
      </Box>

      {/* Condition pip strip: tiny chips so the operator can see at a
          glance which conditions exist and which one they're currently
          viewing. Tapping a chip jumps directly there (chevrons remain
          for sequential paging). Hidden when there's only one condition
          since the indicator would be noise. */}
      {lanes.length > 1 && (
        <Stack direction="row" spacing={1} justifyContent="center" sx={{ flexWrap: 'wrap' }}>
          {lanes.map((lane, idx) => {
            const isCurrent = idx === currentConditionIndex;
            const chipPalette = getPaletteColor(lane.condition.color);
            return (
              <Chip
                key={lane.condition.id}
                label={lane.condition.name || '(unnamed)'}
                onClick={() => setCurrentConditionIndex(idx)}
                size="small"
                variant={isCurrent ? 'filled' : 'outlined'}
                sx={{
                  bgcolor: isCurrent ? chipPalette.bg : 'transparent',
                  color: isCurrent ? chipPalette.fg : 'text.primary',
                  borderColor: chipPalette.bg,
                  fontWeight: isCurrent ? 700 : 500,
                }}
              />
            );
          })}
        </Stack>
      )}

      {/* Single visible Condition. ConditionLane handles the big-button
          + big-countdown rendering when ``variant="focus"``. We pass
          ``hideHeader`` so the lane doesn't double up our navigator,
          and ``hideNonActiveSteps`` so only the actionable step shows. */}
      <Box sx={{ flexGrow: 1, display: 'flex' }}>
        <ConditionLane
          condition={currentLane.condition}
          steps={currentLane.steps}
          activeStepId={activeStepId}
          variant="focus"
          hideHeader
          hideNonActiveSteps
          onStartStep={onStartStep}
          onPauseStep={onPauseStep}
          onResumeStep={onResumeStep}
          onCompleteStep={onCompleteStep}
          onSkipStep={onSkipStep}
          onExtendStep={onExtendStep}
          onPushCondition={
            // Same opt-out semantics as the swimlane: synthetic-main has
            // no real Condition row server-side, so disable the push
            // controls there to avoid a 404. ``undefined`` is the lane's
            // "no controls" signal -- don't replace with a no-op.
            currentLane.condition.id === 'synthetic-main' || !onPushCondition
              ? undefined
              : (delta) =>
                  onPushCondition(
                    currentLane.condition.id,
                    currentLane.condition.name,
                    delta
                  )
          }
        />
      </Box>

      {/* Footer hint. Operators new to the focus view need a one-time
          "swipe or tap chevrons" affordance. We keep it small and
          dismissable-by-ignoring so it doesn't compete with the active
          step's button group. Hidden when there's only one Condition. */}
      {lanes.length > 1 && (
        <Box sx={{ textAlign: 'center', opacity: 0.6 }}>
          <Typography variant="caption">
            Swipe or tap the chevrons to switch conditions.
          </Typography>
        </Box>
      )}

      {/* Defensive: when the visible lane has zero steps + zero active,
          the inner ConditionLane already renders an Alert. We keep a
          parallel notice here in case the parent passed empty lanes
          intentionally (e.g., mid-design preview). */}
      {currentLane.steps.length === 0 && (
        <Alert severity="info" variant="outlined">
          This Condition has no steps yet.
        </Alert>
      )}
    </Box>
  );
};

export default FocusModeRunner;
