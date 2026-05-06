import React, { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
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
  FormHelperText,
  SelectChangeEvent
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import EditIcon from '@mui/icons-material/Edit';
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpward';
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward';
import SaveIcon from '@mui/icons-material/Save';
import apiClient, { Experiment as ApiExperiment, Step as ApiStep } from '../api/client';

interface Step {
  id: string;
  name: string;
  type: string;
  duration: number;
  dependencies: string[];
  notes?: string;
  resourceNeeded?: string;
}

interface Experiment {
  id: string;
  name: string;
  description: string;
  steps: Step[];
}

const newLocalId = () => Math.random().toString(36).substring(2, 9);

const ExperimentDesigner: React.FC = () => {
  const navigate = useNavigate();
  const { id: experimentId } = useParams<{ id?: string }>();
  const isEditing = Boolean(experimentId);

  const [experiment, setExperiment] = useState<Experiment>({
    id: experimentId || newLocalId(),
    name: '',
    description: '',
    steps: []
  });

  const [openStepDialog, setOpenStepDialog] = useState(false);
  const [currentStep, setCurrentStep] = useState<Step | null>(null);
  const [editStepIndex, setEditStepIndex] = useState<number | null>(null);

  const [loading, setLoading] = useState<boolean>(isEditing);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState<boolean>(false);

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
        setExperiment({
          id: data.id,
          name: data.name || '',
          description: data.description || '',
          steps: (data.steps || []).map((s: ApiStep) => ({
            id: s.id,
            name: s.name,
            type: s.type,
            duration: s.duration,
            dependencies: s.dependencies || [],
            notes: s.notes,
            resourceNeeded: s.resourceNeeded,
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

  const handleAddStep = () => {
    setCurrentStep({
      id: Math.random().toString(36).substring(2, 9),
      name: '',
      type: 'fixed_duration',
      duration: 30,
      dependencies: []
    });
    setEditStepIndex(null);
    setOpenStepDialog(true);
  };

  const handleEditStep = (index: number) => {
    setCurrentStep({...experiment.steps[index]});
    setEditStepIndex(index);
    setOpenStepDialog(true);
  };

  const handleDeleteStep = (index: number) => {
    const newSteps = [...experiment.steps];
    newSteps.splice(index, 1);
    
    // Update dependencies in other steps
    const deletedStepId = experiment.steps[index].id;
    const updatedSteps = newSteps.map(step => ({
      ...step,
      dependencies: step.dependencies.filter(id => id !== deletedStepId)
    }));
    
    setExperiment({...experiment, steps: updatedSteps});
  };

  const handleSaveStep = () => {
    if (!currentStep) return;
    
    const newSteps = [...experiment.steps];
    if (editStepIndex !== null) {
      newSteps[editStepIndex] = currentStep;
    } else {
      newSteps.push(currentStep);
    }
    
    setExperiment({...experiment, steps: newSteps});
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
    setExperiment({...experiment, steps: newSteps});
  };

  const handleStepDurationChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!currentStep) return;
    const duration = parseInt(e.target.value, 10) || 0;
    setCurrentStep({...currentStep, duration});
  };

  const handleStepTypeChange = (e: SelectChangeEvent) => {
    if (!currentStep) return;
    setCurrentStep({...currentStep, type: e.target.value});
  };

  const handleSaveExperiment = async () => {
    setSaveError(null);

    // Belt-and-suspenders validation: inputProps={{min: 1}} on the duration
    // field is bypassable via paste/keyboard. Re-check here.
    const invalidStep = experiment.steps.find(
      (s) => !Number.isFinite(s.duration) || s.duration <= 0
    );
    if (invalidStep) {
      setSaveError(
        `Step "${invalidStep.name || 'unnamed'}" must have a duration greater than zero.`
      );
      return;
    }

    // Map to the backend's expected shape. Field names stay camelCase for now;
    // U8 will normalize the wire format to snake_case in a single mechanical pass.
    const payload = {
      name: experiment.name,
      description: experiment.description,
      steps: experiment.steps.map((s) => ({
        id: s.id,
        name: s.name,
        type: s.type,
        duration: s.duration,
        dependencies: s.dependencies,
        notes: s.notes,
        resourceNeeded: s.resourceNeeded,
      })),
    };

    try {
      setSaving(true);
      if (experimentId) {
        await apiClient.updateExperiment(experimentId, payload as Partial<ApiExperiment>);
      } else {
        await apiClient.createExperiment(payload as Omit<ApiExperiment, 'id'>);
      }
      navigate('/');
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

        <Paper sx={{ p: 3, mb: 4 }}>
          <Grid container spacing={3}>
            <Grid item xs={12}>
              <TextField
                fullWidth
                label="Experiment Name"
                value={experiment.name}
                onChange={(e) => setExperiment({...experiment, name: e.target.value})}
                variant="outlined"
                required
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                fullWidth
                label="Description"
                value={experiment.description}
                onChange={(e) => setExperiment({...experiment, description: e.target.value})}
                variant="outlined"
                multiline
                rows={3}
              />
            </Grid>
          </Grid>
        </Paper>
        
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Typography variant="h5" component="h2">
            Experiment Steps
          </Typography>
          <Button 
            variant="contained" 
            startIcon={<AddIcon />}
            onClick={handleAddStep}
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
          <List component={Paper}>
            {experiment.steps.map((step, index) => (
              <React.Fragment key={step.id}>
                {index > 0 && <Divider />}
                <ListItem
                  secondaryAction={
                    <Box>
                      <IconButton 
                        edge="end" 
                        aria-label="move up"
                        disabled={index === 0}
                        onClick={() => handleMoveStep(index, 'up')}
                      >
                        <ArrowUpwardIcon />
                      </IconButton>
                      <IconButton 
                        edge="end" 
                        aria-label="move down"
                        disabled={index === experiment.steps.length - 1}
                        onClick={() => handleMoveStep(index, 'down')}
                      >
                        <ArrowDownwardIcon />
                      </IconButton>
                      <IconButton 
                        edge="end" 
                        aria-label="edit"
                        onClick={() => handleEditStep(index)}
                      >
                        <EditIcon />
                      </IconButton>
                      <IconButton 
                        edge="end" 
                        aria-label="delete"
                        onClick={() => handleDeleteStep(index)}
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
                          Type: {step.type} | Duration: {step.duration} min
                        </Typography>
                        {step.dependencies.length > 0 && (
                          <Typography component="span" variant="body2" display="block">
                            Dependencies: {step.dependencies.map(depId => {
                              const depStep = experiment.steps.find(s => s.id === depId);
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
                onChange={(e) => currentStep && setCurrentStep({...currentStep, name: e.target.value})}
                variant="outlined"
                required
              />
            </Grid>
            <Grid item xs={12} sm={6}>
              <FormControl fullWidth>
                <InputLabel id="step-type-label">Step Type</InputLabel>
                <Select
                  labelId="step-type-label"
                  value={currentStep?.type || ''}
                  label="Step Type"
                  onChange={handleStepTypeChange}
                >
                  <MenuItem value="fixed_duration">Fixed Duration</MenuItem>
                  <MenuItem value="task">Task (User Driven)</MenuItem>
                  <MenuItem value="fixed_start">Fixed Start Time</MenuItem>
                  <MenuItem value="automated_task">Automated Task</MenuItem>
                </Select>
                <FormHelperText>
                  {currentStep?.type === 'fixed_duration' && 'Timer countdown; cannot pause/stop; signals completion'}
                  {currentStep?.type === 'task' && 'User-driven; tracks elapsed time; can pause/stop; requires attention'}
                  {currentStep?.type === 'fixed_start' && 'Timer count-up; cannot pause/stop; duration sets earliest start for dependents'}
                  {currentStep?.type === 'automated_task' && 'Runs for set time; cannot pause; blocks resource but frees user'}
                </FormHelperText>
              </FormControl>
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                label="Duration (minutes)"
                type="number"
                value={currentStep?.duration || 0}
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
                  onChange={(e) => currentStep && setCurrentStep({
                    ...currentStep, 
                    dependencies: typeof e.target.value === 'string' 
                      ? e.target.value.split(',') 
                      : e.target.value
                  })}
                  renderValue={(selected) => {
                    if (Array.isArray(selected)) {
                      return selected.map(depId => {
                        const depStep = experiment.steps.find(s => s.id === depId);
                        return depStep ? depStep.name : depId;
                      }).join(', ');
                    }
                    return '';
                  }}
                >
                  {experiment.steps
                    .filter(step => !currentStep || step.id !== currentStep.id)
                    .map((step) => (
                      <MenuItem key={step.id} value={step.id}>
                        {step.name}
                      </MenuItem>
                    ))}
                </Select>
                <FormHelperText>Steps that must complete before this step can start</FormHelperText>
              </FormControl>
            </Grid>
            <Grid item xs={12}>
              <TextField
                fullWidth
                label="Resource Needed"
                value={currentStep?.resourceNeeded || ''}
                onChange={(e) => currentStep && setCurrentStep({...currentStep, resourceNeeded: e.target.value})}
                variant="outlined"
                placeholder="e.g., microscope, user_attention, lab_bench"
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                fullWidth
                label="Notes"
                value={currentStep?.notes || ''}
                onChange={(e) => currentStep && setCurrentStep({...currentStep, notes: e.target.value})}
                variant="outlined"
                multiline
                rows={3}
              />
            </Grid>
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
    </Container>
  );
};

export default ExperimentDesigner; 