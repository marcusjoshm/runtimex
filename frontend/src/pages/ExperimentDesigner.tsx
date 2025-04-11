import React, { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  Box,
  Button,
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
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpward';
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward';
import SaveIcon from '@mui/icons-material/Save';

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

const ExperimentDesigner: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const experimentId = new URLSearchParams(location.search).get('id');
  
  const [experiment, setExperiment] = useState<Experiment>({
    id: experimentId || Math.random().toString(36).substring(2, 9),
    name: '',
    description: '',
    steps: []
  });

  const [openStepDialog, setOpenStepDialog] = useState(false);
  const [currentStep, setCurrentStep] = useState<Step | null>(null);
  const [editStepIndex, setEditStepIndex] = useState<number | null>(null);

  // Load experiment data if editing an existing one
  useEffect(() => {
    if (experimentId) {
      // This would be an API call in a real app
      // Mock data for now
      if (experimentId === '1') {
        setExperiment({
          id: '1',
          name: 'Cell Culture Protocol',
          description: 'Standard protocol for maintaining cell cultures',
          steps: [
            {
              id: 's1',
              name: 'Prepare media',
              type: 'task',
              duration: 15,
              dependencies: [],
              resourceNeeded: 'lab_bench'
            },
            {
              id: 's2',
              name: 'Thaw cells',
              type: 'fixed_duration',
              duration: 30,
              dependencies: ['s1'],
              resourceNeeded: 'water_bath'
            }
          ]
        });
      }
    }
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

  const handleSaveExperiment = () => {
    // This would be an API call in a real app
    console.log('Saving experiment:', experiment);
    alert('Experiment saved successfully!');
    navigate('/');
  };

  return (
    <Container maxWidth="lg">
      <Box sx={{ my: 4 }}>
        <Typography variant="h4" component="h1" gutterBottom>
          {experimentId ? 'Edit Experiment' : 'Create New Experiment'}
        </Typography>
        
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
            disabled={!experiment.name || experiment.steps.length === 0}
          >
            Save Experiment
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