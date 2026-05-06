import React, { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Container,
  TextField,
  Typography,
  Paper,
  Grid,
  Select,
  MenuItem,
  InputLabel,
  FormControl,
  Divider,
  IconButton,
  List,
  ListItem,
  ListItemText,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  DialogContentText,
  FormHelperText,
  FormControlLabel,
  Switch,
  SelectChangeEvent,
  Stack,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import EditIcon from '@mui/icons-material/Edit';
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpward';
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward';
import SaveIcon from '@mui/icons-material/Save';
import apiClient, {
  Experiment as ApiExperiment,
  Step as ApiStep,
  Condition as ApiCondition,
  Conflict,
} from '../api/client';
import ConditionEditor from '../components/ConditionEditor';
import { getPaletteColor } from '../components/ConditionPaletteSwatch';

// Local Step shape used by the Designer's UI state. The form lets the user
// enter duration in MINUTES (which is the natural unit when designing a
// protocol); we convert to seconds at save time when constructing the
// snake_case wire payload (U8). Field names mirror the wire shape so the
// load+save round-trip is mechanical.
interface Step {
  id: string;
  name: string;
  step_type: string;
  // Designer-local: minutes. Convert to ``duration_seconds`` on save and
  // from ``duration_seconds`` on load.
  duration_minutes: number;
  dependencies: string[];
  notes?: string;
  resource_required?: string;
  // Each Step belongs to exactly one Condition. We default new Steps to the
  // currently-first Condition (or a Main Condition we'll auto-create) so the
  // user never has to pick on every Add Step click.
  condition_id: string;
  // U3 cascading time: opt-in inherit directive. Stored on the Designer-local
  // state as the same string the wire carries -- "previous" (the only value
  // the Designer UI surfaces today) or undefined for "no inherit". The
  // toggle in the step editor writes "previous"; we deliberately don't expose
  // a sibling-id picker yet because the brainstorm's primary case is the
  // wash -> re-incubate adjacency.
  inherits_elapsed_from?: string;
}

interface Experiment {
  id: string;
  name: string;
  description: string;
  steps: Step[];
  // Conditions live here in local state too -- the user can add/edit/reorder
  // them in the form and we send the whole array on save (U1's wire shape).
  conditions: ApiCondition[];
}

const newLocalId = () => Math.random().toString(36).substring(2, 9);

// Build a fresh Condition dataclass for the Designer's local state. We make
// up an ID client-side so the user can immediately reference it from new
// Steps' condition_id without waiting for a save round-trip; the backend
// upserts by ID so the value sticks across the POST/PUT.
const newCondition = (
  experimentId: string,
  defaults: Partial<ApiCondition> = {}
): ApiCondition => ({
  id: defaults.id ?? newLocalId(),
  experiment_id: experimentId,
  name: defaults.name ?? '',
  color: defaults.color ?? 'slate',
  order_index: defaults.order_index ?? 0,
  description: defaults.description,
});

const ExperimentDesigner: React.FC = () => {
  const navigate = useNavigate();
  const { id: experimentId } = useParams<{ id?: string }>();
  const isEditing = Boolean(experimentId);

  // The local experiment state always has at least one Condition. If the
  // user is creating a brand-new Experiment we seed with a default "Main"
  // Condition so the per-step Condition dropdown is never empty.
  const initialExperimentId = experimentId || newLocalId();
  const [experiment, setExperiment] = useState<Experiment>({
    id: initialExperimentId,
    name: '',
    description: '',
    steps: [],
    conditions: [
      newCondition(initialExperimentId, { name: 'Main', color: 'slate', order_index: 0 }),
    ],
  });

  const [openStepDialog, setOpenStepDialog] = useState(false);
  const [currentStep, setCurrentStep] = useState<Step | null>(null);
  const [editStepIndex, setEditStepIndex] = useState<number | null>(null);

  // Condition editor state. `conditionDraft` is the value passed into
  // <ConditionEditor>; `editingConditionIndex` tells us whether to update
  // an existing Condition (-1 = adding new) on save.
  const [openConditionDialog, setOpenConditionDialog] = useState(false);
  const [conditionDraft, setConditionDraft] = useState<ApiCondition | null>(null);
  const [editingConditionIndex, setEditingConditionIndex] = useState<number>(-1);

  // Cross-condition Step-move confirmation dialog. When the user changes a
  // Step's Condition while it has dependencies, we stash the pending change
  // here, ask "are you sure (deps will be stripped)?", and apply on confirm.
  // Cancel reverts the dropdown to the previous condition_id.
  const [conditionMoveConfirm, setConditionMoveConfirm] = useState<{
    fromConditionId: string;
    toConditionId: string;
    dependencyCount: number;
  } | null>(null);

  const [loading, setLoading] = useState<boolean>(isEditing);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState<boolean>(false);
  // Conflicts returned by the backend on save (U6). When non-empty, we
  // intentionally suppress the navigate('/') so the user sees the warning
  // and can decide whether to fix the schedule before leaving the page.
  // Design choice: suppress-navigate is the simplest of the two options
  // sketched in the plan -- a transient localStorage handoff to Home would
  // need a corresponding read site, and a snackbar-then-navigate fights
  // against the user's eyes (a snackbar that disappears before they read it
  // is worse than no snackbar). Forcing them to dismiss the alert by
  // clicking "Back to home" gives them an unmissable signal.
  const [conflicts, setConflicts] = useState<Conflict[]>([]);

  // Load experiment data if editing an existing one
  useEffect(() => {
    let cancelled = false;
    if (!experimentId) {
      setLoading(false);
      return;
    }

    setLoading(true);
    setLoadError(null);

    apiClient.getExperiment(experimentId)
      .then((data: ApiExperiment) => {
        if (cancelled) return;
        // Server-side every persisted experiment has at least one Condition
        // (U1 backfill ensures Main exists). But guard against an empty
        // payload anyway so the dropdown isn't blank for a corrupt fetch.
        const loadedConditions: ApiCondition[] = (data.conditions ?? []).slice().sort(
          (a, b) => a.order_index - b.order_index
        );
        const conditionsToUse: ApiCondition[] =
          loadedConditions.length > 0
            ? loadedConditions
            : [
                newCondition(data.id, {
                  name: 'Main',
                  color: 'slate',
                  order_index: 0,
                }),
              ];
        const fallbackConditionId = conditionsToUse[0].id;

        setExperiment({
          id: data.id,
          name: data.name || '',
          description: data.description || '',
          conditions: conditionsToUse,
          steps: (data.steps || []).map((s: ApiStep) => ({
            id: s.id,
            name: s.name,
            step_type: s.step_type,
            // Wire format is seconds (U8); the Designer edits in minutes.
            // We round up sub-minute durations to 1 so an existing
            // half-minute step doesn't snap to 0 on first edit.
            duration_minutes: s.duration_seconds
              ? Math.max(1, Math.round(s.duration_seconds / 60))
              : 0,
            dependencies: s.dependencies || [],
            notes: s.notes,
            resource_required: s.resource_required,
            condition_id: s.condition_id || fallbackConditionId,
            inherits_elapsed_from: s.inherits_elapsed_from,
          })),
        });
      })
      .catch((err: any) => {
        if (cancelled) return;
        setLoadError(err.response?.data?.error || 'Failed to load experiment');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [experimentId]);

  // ------------------------------------------------------------------
  // Condition handlers
  // ------------------------------------------------------------------
  const handleAddCondition = () => {
    const nextOrder = experiment.conditions.length;
    setConditionDraft(
      newCondition(experiment.id, {
        name: '',
        color: 'slate',
        order_index: nextOrder,
      })
    );
    setEditingConditionIndex(-1);
    setOpenConditionDialog(true);
  };

  const handleEditCondition = (index: number) => {
    setConditionDraft({ ...experiment.conditions[index] });
    setEditingConditionIndex(index);
    setOpenConditionDialog(true);
  };

  const handleSaveCondition = (saved: ApiCondition) => {
    setExperiment((prev) => {
      const conditions = [...prev.conditions];
      if (editingConditionIndex >= 0) {
        conditions[editingConditionIndex] = saved;
      } else {
        conditions.push(saved);
      }
      return { ...prev, conditions };
    });
    setOpenConditionDialog(false);
    setConditionDraft(null);
    setEditingConditionIndex(-1);
  };

  const handleDeleteCondition = (index: number) => {
    const condition = experiment.conditions[index];
    if (!condition) return;
    // Refuse to delete the last Condition -- every Step needs to belong
    // somewhere, and the backend rejects an empty-Conditions experiment.
    if (experiment.conditions.length <= 1) {
      setSaveError('At least one Condition is required.');
      return;
    }
    // Refuse to delete a Condition that still has Steps assigned. The user
    // must move them out first; auto-reassigning to a sibling would silently
    // mix protocols, which is exactly what Conditions exist to prevent.
    const stepsInCondition = experiment.steps.filter(
      (s) => s.condition_id === condition.id
    );
    if (stepsInCondition.length > 0) {
      setSaveError(
        `Cannot delete "${condition.name}" -- ${stepsInCondition.length} step(s) still belong to it. Move or delete them first.`
      );
      return;
    }
    setSaveError(null);
    setExperiment((prev) => {
      const conditions = prev.conditions.filter((_, i) => i !== index);
      // Renumber order_index so subsequent reorder operations stay sensible.
      conditions.forEach((c, i) => {
        c.order_index = i;
      });
      return { ...prev, conditions };
    });
  };

  const handleMoveCondition = (index: number, direction: 'up' | 'down') => {
    if (
      (direction === 'up' && index === 0) ||
      (direction === 'down' && index === experiment.conditions.length - 1)
    ) {
      return;
    }
    setExperiment((prev) => {
      const conditions = [...prev.conditions];
      const targetIndex = direction === 'up' ? index - 1 : index + 1;
      [conditions[index], conditions[targetIndex]] = [
        conditions[targetIndex],
        conditions[index],
      ];
      // Re-derive order_index from array position.
      conditions.forEach((c, i) => {
        c.order_index = i;
      });
      return { ...prev, conditions };
    });
  };

  // ------------------------------------------------------------------
  // Step handlers
  // ------------------------------------------------------------------
  const defaultConditionId = (): string =>
    experiment.conditions[0]?.id ?? '';

  const handleAddStep = () => {
    setCurrentStep({
      id: Math.random().toString(36).substring(2, 9),
      name: '',
      step_type: 'fixed_duration',
      duration_minutes: 30,
      dependencies: [],
      condition_id: defaultConditionId(),
    });
    setEditStepIndex(null);
    setOpenStepDialog(true);
  };

  const handleEditStep = (index: number) => {
    setCurrentStep({ ...experiment.steps[index] });
    setEditStepIndex(index);
    setOpenStepDialog(true);
  };

  const handleDeleteStep = (index: number) => {
    const newSteps = [...experiment.steps];
    newSteps.splice(index, 1);

    // Update dependencies in other steps
    const deletedStepId = experiment.steps[index].id;
    const updatedSteps = newSteps.map((step) => ({
      ...step,
      dependencies: step.dependencies.filter((id) => id !== deletedStepId),
    }));

    setExperiment({ ...experiment, steps: updatedSteps });
  };

  const handleSaveStep = () => {
    if (!currentStep) return;

    const newSteps = [...experiment.steps];
    if (editStepIndex !== null) {
      newSteps[editStepIndex] = currentStep;
    } else {
      newSteps.push(currentStep);
    }

    setExperiment({ ...experiment, steps: newSteps });
    setOpenStepDialog(false);
    setCurrentStep(null);
    setEditStepIndex(null);
  };

  const handleMoveStep = (index: number, direction: 'up' | 'down') => {
    if (
      (direction === 'up' && index === 0) ||
      (direction === 'down' && index === experiment.steps.length - 1)
    ) {
      return;
    }

    const newSteps = [...experiment.steps];
    const targetIndex = direction === 'up' ? index - 1 : index + 1;

    [newSteps[index], newSteps[targetIndex]] = [newSteps[targetIndex], newSteps[index]];
    setExperiment({ ...experiment, steps: newSteps });
  };

  const handleStepDurationChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!currentStep) return;
    const duration_minutes = parseInt(e.target.value, 10) || 0;
    setCurrentStep({ ...currentStep, duration_minutes });
  };

  const handleStepTypeChange = (e: SelectChangeEvent) => {
    if (!currentStep) return;
    setCurrentStep({ ...currentStep, step_type: e.target.value });
  };

  // When the user picks a different Condition for the step in the editor:
  // if the step has dependencies we stash the move and pop a confirmation.
  // The backend rejects cross-condition deps (U1) so we strip them at the
  // client to keep the round-trip clean.
  const handleStepConditionChange = (e: SelectChangeEvent) => {
    if (!currentStep) return;
    const newConditionId = e.target.value;
    if (newConditionId === currentStep.condition_id) return;
    if (currentStep.dependencies.length > 0) {
      setConditionMoveConfirm({
        fromConditionId: currentStep.condition_id,
        toConditionId: newConditionId,
        dependencyCount: currentStep.dependencies.length,
      });
      return;
    }
    setCurrentStep({ ...currentStep, condition_id: newConditionId });
  };

  const handleConfirmConditionMove = () => {
    if (!currentStep || !conditionMoveConfirm) return;
    setCurrentStep({
      ...currentStep,
      condition_id: conditionMoveConfirm.toConditionId,
      dependencies: [],
    });
    setConditionMoveConfirm(null);
  };

  const handleCancelConditionMove = () => {
    setConditionMoveConfirm(null);
  };

  const handleSaveExperiment = async () => {
    setSaveError(null);

    // Belt-and-suspenders validation: inputProps={{min: 1}} on the duration
    // field is bypassable via paste/keyboard. Re-check here.
    const invalidStep = experiment.steps.find(
      (s) => !Number.isFinite(s.duration_minutes) || s.duration_minutes <= 0
    );
    if (invalidStep) {
      setSaveError(
        `Step "${invalidStep.name || 'unnamed'}" must have a duration greater than zero.`
      );
      return;
    }
    if (experiment.conditions.length === 0) {
      setSaveError('At least one Condition is required.');
      return;
    }
    const blankNamedCondition = experiment.conditions.find((c) => !c.name.trim());
    if (blankNamedCondition) {
      setSaveError('Every Condition must have a name.');
      return;
    }

    // Map to the backend's expected shape (snake_case per U8). Duration is
    // converted minutes -> seconds at the wire boundary so the server can
    // store the canonical timedelta directly.
    const payload = {
      name: experiment.name,
      description: experiment.description,
      conditions: experiment.conditions.map((c, i) => ({
        id: c.id,
        name: c.name,
        color: c.color,
        order_index: i, // canonicalize order from array position on save
        description: c.description,
      })),
      steps: experiment.steps.map((s) => ({
        id: s.id,
        name: s.name,
        step_type: s.step_type,
        duration_seconds: s.duration_minutes * 60,
        dependencies: s.dependencies,
        notes: s.notes,
        resource_required: s.resource_required,
        condition_id: s.condition_id,
        // U3: only send the field when the user actually opted in. The
        // serializer round-trips with "skip None" so an undefined here lands
        // as a missing key on the wire.
        ...(s.inherits_elapsed_from
          ? { inherits_elapsed_from: s.inherits_elapsed_from }
          : {}),
      })),
    };

    try {
      setSaving(true);
      // Only the PUT path returns a `conflicts` array today (U6). New
      // experiments don't surface them on POST -- the backend lays out the
      // schedule from "now" and any overlaps are reported on the next save
      // or via GET /api/experiments/<id>/conflicts. If U7 wires conflicts
      // into the POST response too, this branch becomes uniform.
      let saveResultConflicts: Conflict[] = [];
      if (experimentId) {
        const updated = await apiClient.updateExperiment(
          experimentId,
          payload as Partial<ApiExperiment>
        );
        saveResultConflicts = updated.conflicts ?? [];
      } else {
        await apiClient.createExperiment(payload as Omit<ApiExperiment, 'id'>);
      }

      if (saveResultConflicts.length > 0) {
        // Show the warning in place; do NOT navigate. The user sees the
        // alert and can either ignore it (navigate back via the Back button)
        // or fix the schedule and save again.
        setConflicts(saveResultConflicts);
      } else {
        // Clean save: behave as before.
        setConflicts([]);
        navigate('/');
      }
    } catch (err: any) {
      setSaveError(err.response?.data?.error || 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <Container maxWidth="lg">
        <Box sx={{ my: 4, display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 200 }}>
          <CircularProgress />
        </Box>
      </Container>
    );
  }

  if (loadError) {
    return (
      <Container maxWidth="lg">
        <Box sx={{ my: 4 }}>
          <Alert severity="error">{loadError}</Alert>
          <Box sx={{ mt: 2 }}>
            <Button onClick={() => navigate('/')}>Back to Home</Button>
          </Box>
        </Box>
      </Container>
    );
  }

  // Group steps by Condition for the visual layout. We preserve the user's
  // current step ordering within each Condition (by re-using the original
  // index for handleMoveStep / handleDeleteStep / handleEditStep so the
  // existing handlers work unchanged).
  const stepsByCondition: Array<{ condition: ApiCondition; entries: { step: Step; originalIndex: number }[] }> =
    experiment.conditions.map((condition) => ({
      condition,
      entries: experiment.steps
        .map((step, originalIndex) => ({ step, originalIndex }))
        .filter((entry) => entry.step.condition_id === condition.id),
    }));

  // Steps that belong to a Condition that no longer exists locally (shouldn't
  // happen via UI flow but be defensive: if the user deletes a Condition
  // before reassigning a Step we'll show the orphans here so they can fix it).
  const orphanSteps = experiment.steps
    .map((step, originalIndex) => ({ step, originalIndex }))
    .filter(
      (entry) =>
        !experiment.conditions.some((c) => c.id === entry.step.condition_id)
    );

  return (
    <Container maxWidth="lg">
      <Box sx={{ my: 4 }}>
        <Typography variant="h4" component="h1" gutterBottom>
          {experimentId ? 'Edit Experiment' : 'Create New Experiment'}
        </Typography>

        {saveError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {saveError}
          </Alert>
        )}

        {conflicts.length > 0 && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            <Typography variant="subtitle2" gutterBottom>
              Saved with {conflicts.length} resource conflict{conflicts.length === 1 ? '' : 's'}:
            </Typography>
            {conflicts.map((c) => (
              <Typography key={`${c.step_a}-${c.step_b}-${c.resource}`} variant="body2">
                {c.step_a_name} ({c.condition_a_name}) ↔ {c.step_b_name} ({c.condition_b_name}) on {c.resource} ({c.overlap_seconds}s overlap)
              </Typography>
            ))}
          </Alert>
        )}

        <Paper sx={{ p: 3, mb: 4 }}>
          <Grid container spacing={3}>
            <Grid item xs={12}>
              <TextField
                fullWidth
                label="Experiment Name"
                value={experiment.name}
                onChange={(e) => setExperiment({ ...experiment, name: e.target.value })}
                variant="outlined"
                required
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                fullWidth
                label="Description"
                value={experiment.description}
                onChange={(e) => setExperiment({ ...experiment, description: e.target.value })}
                variant="outlined"
                multiline
                rows={3}
              />
            </Grid>
          </Grid>
        </Paper>

        {/* Conditions section.
            Layout choice: above-steps full-width row (rather than a sidebar).
            Reasons: (1) it follows the natural editing order -- users decide
            their conditions before they assign steps to them; (2) the
            existing Designer page is a single-column form, and a true
            sidebar would force MUI Grid layout changes that fight against
            the existing Step list rendering; (3) below it we group the Step
            list by Condition for visual clarity, so the conditions header
            doubles as a legend for the swimlane-shaped step list. */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Typography variant="h5" component="h2">
            Conditions
          </Typography>
          <Button
            variant="outlined"
            startIcon={<AddIcon />}
            onClick={handleAddCondition}
          >
            Add Condition
          </Button>
        </Box>

        <List component={Paper} sx={{ mb: 4 }}>
          {experiment.conditions.map((condition, index) => {
            const palette = getPaletteColor(condition.color);
            const stepCount = experiment.steps.filter(
              (s) => s.condition_id === condition.id
            ).length;
            return (
              <React.Fragment key={condition.id}>
                {index > 0 && <Divider />}
                <ListItem
                  secondaryAction={
                    <Box>
                      <IconButton
                        edge="end"
                        aria-label="move condition up"
                        disabled={index === 0}
                        onClick={() => handleMoveCondition(index, 'up')}
                      >
                        <ArrowUpwardIcon />
                      </IconButton>
                      <IconButton
                        edge="end"
                        aria-label="move condition down"
                        disabled={index === experiment.conditions.length - 1}
                        onClick={() => handleMoveCondition(index, 'down')}
                      >
                        <ArrowDownwardIcon />
                      </IconButton>
                      <IconButton
                        edge="end"
                        aria-label="edit condition"
                        onClick={() => handleEditCondition(index)}
                      >
                        <EditIcon />
                      </IconButton>
                      <IconButton
                        edge="end"
                        aria-label="delete condition"
                        onClick={() => handleDeleteCondition(index)}
                      >
                        <DeleteIcon />
                      </IconButton>
                    </Box>
                  }
                >
                  <Chip
                    label={condition.name || '(unnamed)'}
                    sx={{
                      bgcolor: palette.bg,
                      color: palette.fg,
                      fontWeight: 600,
                      mr: 2,
                    }}
                  />
                  <ListItemText
                    primary={`${stepCount} step${stepCount === 1 ? '' : 's'}`}
                    secondary={condition.description || undefined}
                  />
                </ListItem>
              </React.Fragment>
            );
          })}
        </List>

        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Typography variant="h5" component="h2">
            Experiment Steps
          </Typography>
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={handleAddStep}
            disabled={experiment.conditions.length === 0}
          >
            Add Step
          </Button>
        </Box>

        {experiment.steps.length === 0 ? (
          <Paper sx={{ p: 3, textAlign: 'center' }}>
            <Typography color="text.secondary">
              No steps yet. Click "Add Step" to create your first step.
            </Typography>
          </Paper>
        ) : (
          <Stack spacing={3}>
            {stepsByCondition.map(({ condition, entries }) => {
              const palette = getPaletteColor(condition.color);
              return (
                <Paper key={condition.id} sx={{ overflow: 'hidden' }}>
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
                    <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                      {condition.name || '(unnamed)'}
                    </Typography>
                    <Typography variant="caption" sx={{ opacity: 0.85 }}>
                      ({entries.length} step{entries.length === 1 ? '' : 's'})
                    </Typography>
                  </Box>
                  {entries.length === 0 ? (
                    <Box sx={{ p: 2 }}>
                      <Typography variant="body2" color="text.secondary">
                        No steps in this condition yet.
                      </Typography>
                    </Box>
                  ) : (
                    <List disablePadding>
                      {entries.map(({ step, originalIndex }, localIndex) => (
                        <React.Fragment key={step.id}>
                          {localIndex > 0 && <Divider />}
                          <ListItem
                            secondaryAction={
                              <Box>
                                <IconButton
                                  edge="end"
                                  aria-label="move up"
                                  disabled={originalIndex === 0}
                                  onClick={() => handleMoveStep(originalIndex, 'up')}
                                >
                                  <ArrowUpwardIcon />
                                </IconButton>
                                <IconButton
                                  edge="end"
                                  aria-label="move down"
                                  disabled={originalIndex === experiment.steps.length - 1}
                                  onClick={() => handleMoveStep(originalIndex, 'down')}
                                >
                                  <ArrowDownwardIcon />
                                </IconButton>
                                <IconButton
                                  edge="end"
                                  aria-label="edit"
                                  onClick={() => handleEditStep(originalIndex)}
                                >
                                  <EditIcon />
                                </IconButton>
                                <IconButton
                                  edge="end"
                                  aria-label="delete"
                                  onClick={() => handleDeleteStep(originalIndex)}
                                >
                                  <DeleteIcon />
                                </IconButton>
                              </Box>
                            }
                          >
                            <ListItemText
                              primary={step.name}
                              secondary={
                                <>
                                  <Typography component="span" variant="body2" color="text.primary">
                                    Type: {step.step_type} | Duration: {step.duration_minutes} min
                                  </Typography>
                                  {step.dependencies.length > 0 && (
                                    <Typography component="span" variant="body2" display="block">
                                      Dependencies: {step.dependencies.map((depId) => {
                                        const depStep = experiment.steps.find((s) => s.id === depId);
                                        return depStep ? depStep.name : depId;
                                      }).join(', ')}
                                    </Typography>
                                  )}
                                </>
                              }
                            />
                          </ListItem>
                        </React.Fragment>
                      ))}
                    </List>
                  )}
                </Paper>
              );
            })}
            {orphanSteps.length > 0 && (
              <Paper sx={{ overflow: 'hidden' }}>
                <Box sx={{ bgcolor: 'error.main', color: 'error.contrastText', px: 2, py: 1 }}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                    Orphan steps (no Condition)
                  </Typography>
                </Box>
                <List disablePadding>
                  {orphanSteps.map(({ step, originalIndex }) => (
                    <ListItem
                      key={step.id}
                      secondaryAction={
                        <IconButton aria-label="edit" onClick={() => handleEditStep(originalIndex)}>
                          <EditIcon />
                        </IconButton>
                      }
                    >
                      <ListItemText primary={step.name} secondary="Reassign this step to a Condition." />
                    </ListItem>
                  ))}
                </List>
              </Paper>
            )}
          </Stack>
        )}

        <Box sx={{ mt: 4, display: 'flex', justifyContent: 'flex-end' }}>
          <Button
            variant="contained"
            color="primary"
            startIcon={<SaveIcon />}
            onClick={handleSaveExperiment}
            disabled={!experiment.name || experiment.steps.length === 0 || saving}
          >
            {saving ? 'Saving...' : 'Save Experiment'}
          </Button>
        </Box>
      </Box>

      {/* Step Dialog */}
      <Dialog
        open={openStepDialog}
        onClose={() => setOpenStepDialog(false)}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle>
          {editStepIndex !== null ? 'Edit Step' : 'Add New Step'}
        </DialogTitle>
        <DialogContent>
          <Grid container spacing={3} sx={{ mt: 0 }}>
            <Grid item xs={12}>
              <TextField
                fullWidth
                label="Step Name"
                value={currentStep?.name || ''}
                onChange={(e) =>
                  currentStep && setCurrentStep({ ...currentStep, name: e.target.value })
                }
                variant="outlined"
                required
              />
            </Grid>
            <Grid item xs={12} sm={6}>
              <FormControl fullWidth>
                <InputLabel id="step-condition-label">Condition</InputLabel>
                <Select
                  labelId="step-condition-label"
                  value={currentStep?.condition_id || ''}
                  label="Condition"
                  onChange={handleStepConditionChange}
                >
                  {experiment.conditions.map((c) => (
                    <MenuItem key={c.id} value={c.id}>
                      {c.name || '(unnamed)'}
                    </MenuItem>
                  ))}
                </Select>
                <FormHelperText>
                  Cross-condition dependencies are not allowed; moving a step to another
                  condition will strip its existing dependencies.
                </FormHelperText>
              </FormControl>
            </Grid>
            <Grid item xs={12} sm={6}>
              <FormControl fullWidth>
                <InputLabel id="step-type-label">Step Type</InputLabel>
                <Select
                  labelId="step-type-label"
                  value={currentStep?.step_type || ''}
                  label="Step Type"
                  onChange={handleStepTypeChange}
                >
                  <MenuItem value="fixed_duration">Fixed Duration</MenuItem>
                  <MenuItem value="task">Task (User Driven)</MenuItem>
                  <MenuItem value="fixed_start">Fixed Start Time</MenuItem>
                  <MenuItem value="automated_task">Automated Task</MenuItem>
                </Select>
                <FormHelperText>
                  {currentStep?.step_type === 'fixed_duration' && 'Timer countdown; cannot pause/stop; signals completion'}
                  {currentStep?.step_type === 'task' && 'User-driven; tracks elapsed time; can pause/stop; requires attention'}
                  {currentStep?.step_type === 'fixed_start' && 'Timer count-up; cannot pause/stop; duration sets earliest start for dependents'}
                  {currentStep?.step_type === 'automated_task' && 'Runs for set time; cannot pause; blocks resource but frees user'}
                </FormHelperText>
              </FormControl>
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                label="Duration (minutes)"
                type="number"
                value={currentStep?.duration_minutes || 0}
                onChange={handleStepDurationChange}
                variant="outlined"
                required
                inputProps={{ min: 1 }}
              />
            </Grid>
            <Grid item xs={12}>
              <FormControl fullWidth>
                <InputLabel id="dependencies-label">Dependencies</InputLabel>
                <Select
                  labelId="dependencies-label"
                  multiple
                  value={currentStep?.dependencies || []}
                  label="Dependencies"
                  onChange={(e) =>
                    currentStep &&
                    setCurrentStep({
                      ...currentStep,
                      dependencies:
                        typeof e.target.value === 'string'
                          ? e.target.value.split(',')
                          : e.target.value,
                    })
                  }
                  renderValue={(selected) => {
                    if (Array.isArray(selected)) {
                      return selected
                        .map((depId) => {
                          const depStep = experiment.steps.find((s) => s.id === depId);
                          return depStep ? depStep.name : depId;
                        })
                        .join(', ');
                    }
                    return '';
                  }}
                >
                  {experiment.steps
                    // Only steps in the SAME Condition can be dependencies (U1 contract).
                    // The backend rejects cross-condition deps, so don't even show them
                    // as choices in the dropdown.
                    .filter(
                      (step) =>
                        (!currentStep || step.id !== currentStep.id) &&
                        currentStep &&
                        step.condition_id === currentStep.condition_id
                    )
                    .map((step) => (
                      <MenuItem key={step.id} value={step.id}>
                        {step.name}
                      </MenuItem>
                    ))}
                </Select>
                <FormHelperText>
                  Steps in the same Condition that must complete before this step can start
                </FormHelperText>
              </FormControl>
            </Grid>
            <Grid item xs={12}>
              <TextField
                fullWidth
                label="Resource Needed"
                value={currentStep?.resource_required || ''}
                onChange={(e) =>
                  currentStep && setCurrentStep({ ...currentStep, resource_required: e.target.value })
                }
                variant="outlined"
                placeholder="e.g., microscope, user_attention, lab_bench"
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                fullWidth
                label="Notes"
                value={currentStep?.notes || ''}
                onChange={(e) =>
                  currentStep && setCurrentStep({ ...currentStep, notes: e.target.value })
                }
                variant="outlined"
                multiline
                rows={3}
              />
            </Grid>
            {/* U3 cascading time: only surface the toggle when the step has
                at least one preceding sibling in its Condition. For the first
                step in a Condition there's nothing to inherit from -- hiding
                the control prevents the user from setting a directive that
                would silently no-op at START (with a warning log on the
                server). The "preceding" check uses the live editor state, so
                reordering steps in the Designer updates eligibility without
                a save round-trip. */}
            {currentStep && (() => {
              const sameConditionSteps = experiment.steps.filter(
                (s) => s.condition_id === currentStep.condition_id
              );
              const indexInCondition = sameConditionSteps.findIndex(
                (s) => s.id === currentStep.id
              );
              // For a brand-new step (not yet committed to experiment.steps)
              // ``editStepIndex`` is null and the step's id won't match any
              // sibling. Treat that as "appended at the end of the
              // condition", so any existing sibling counts as preceding.
              const hasPreceding =
                editStepIndex === null
                  ? sameConditionSteps.length > 0
                  : indexInCondition > 0;
              if (!hasPreceding) return null;
              const inheritOn = currentStep.inherits_elapsed_from === 'previous';
              return (
                <Grid item xs={12}>
                  <FormControlLabel
                    control={
                      <Switch
                        checked={inheritOn}
                        onChange={(e) =>
                          setCurrentStep({
                            ...currentStep,
                            inherits_elapsed_from: e.target.checked
                              ? 'previous'
                              : undefined,
                          })
                        }
                      />
                    }
                    label="Inherit elapsed time from previous step"
                  />
                  <FormHelperText>
                    When enabled, this step's countdown begins as if the previous
                    step's elapsed time has already accrued (e.g., a 4-minute wash
                    eats into a 30-minute re-incubation, leaving 26 minutes).
                  </FormHelperText>
                </Grid>
              );
            })()}
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpenStepDialog(false)}>Cancel</Button>
          <Button
            onClick={handleSaveStep}
            disabled={!currentStep?.name}
            variant="contained"
          >
            Save Step
          </Button>
        </DialogActions>
      </Dialog>

      {/* Condition editor dialog */}
      {conditionDraft && (
        <ConditionEditor
          condition={conditionDraft}
          open={openConditionDialog}
          onSave={handleSaveCondition}
          onCancel={() => {
            setOpenConditionDialog(false);
            setConditionDraft(null);
            setEditingConditionIndex(-1);
          }}
          title={editingConditionIndex >= 0 ? 'Edit Condition' : 'Add Condition'}
        />
      )}

      {/* Cross-condition move confirmation dialog */}
      <Dialog open={Boolean(conditionMoveConfirm)} onClose={handleCancelConditionMove}>
        <DialogTitle>Move step to a different Condition?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Moving this step to a new Condition will remove its{' '}
            {conditionMoveConfirm?.dependencyCount ?? 0} dependency
            {conditionMoveConfirm?.dependencyCount === 1 ? '' : 'ies'}. Cross-condition
            dependencies are not allowed. Continue?
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCancelConditionMove}>Cancel</Button>
          <Button onClick={handleConfirmConditionMove} variant="contained" color="warning">
            Move and strip dependencies
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
};

export default ExperimentDesigner;
