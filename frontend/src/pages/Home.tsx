import React, { useState, useEffect } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { 
  Box, 
  Button, 
  Card, 
  CardContent, 
  CardActions, 
  Container, 
  Grid, 
  Typography,
  Fab,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  CircularProgress
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import EditIcon from '@mui/icons-material/Edit';
import apiClient, { Experiment } from '../api/client';

const Home: React.FC = () => {
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openNewDialog, setOpenNewDialog] = useState(false);
  const [newExperimentName, setNewExperimentName] = useState('');
  const [newExperimentDesc, setNewExperimentDesc] = useState('');

  // Load experiments from API
  useEffect(() => {
    const fetchExperiments = async () => {
      try {
        setLoading(true);
        const data = await apiClient.getExperiments();
        setExperiments(data);
        setError(null);
      } catch (err) {
        console.error('Failed to fetch experiments:', err);
        setError('Failed to load experiments. Please try again later.');
        // Fall back to mock data in development
        if (process.env.NODE_ENV === 'development') {
          setExperiments([
            {
              id: '1',
              name: 'Cell Culture Protocol',
              description: 'Standard protocol for maintaining cell cultures',
              steps: []
            },
            {
              id: '2',
              name: 'Western Blot',
              description: 'Western blotting for protein detection',
              steps: []
            }
          ]);
        }
      } finally {
        setLoading(false);
      }
    };
    
    fetchExperiments();
  }, []);

  const handleCreateNewExperiment = async () => {
    try {
      const newExperiment = await apiClient.createExperiment({
        name: newExperimentName,
        description: newExperimentDesc,
        steps: []
      });
      
      setExperiments([...experiments, newExperiment]);
      setOpenNewDialog(false);
      setNewExperimentName('');
      setNewExperimentDesc('');
    } catch (err) {
      console.error('Failed to create experiment:', err);
      alert('Failed to create experiment. Please try again.');
    }
  };

  return (
    <Container maxWidth="lg">
      <Box sx={{ my: 4 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
          <Typography variant="h4" component="h1" gutterBottom>
            My Experiments
          </Typography>
          <Fab 
            color="primary" 
            aria-label="add"
            onClick={() => setOpenNewDialog(true)}
          >
            <AddIcon />
          </Fab>
        </Box>
      
        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}>
            <CircularProgress />
          </Box>
        ) : error ? (
          <Box sx={{ p: 3, textAlign: 'center' }}>
            <Typography color="error">{error}</Typography>
          </Box>
        ) : experiments.length === 0 ? (
          <Box sx={{ p: 3, textAlign: 'center' }}>
            <Typography>No experiments yet. Create your first experiment by clicking the + button.</Typography>
          </Box>
        ) : (
          <Grid container spacing={3}>
            {experiments.map((experiment) => (
              <Grid item xs={12} sm={6} md={4} key={experiment.id}>
                <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
                  <CardContent sx={{ flexGrow: 1 }}>
                    <Typography gutterBottom variant="h5" component="h2">
                      {experiment.name}
                    </Typography>
                    <Typography variant="body2" sx={{ mt: 2 }}>
                      {experiment.description}
                    </Typography>
                    {experiment.steps && (
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                        {experiment.steps.length} steps
                      </Typography>
                    )}
                  </CardContent>
                  <CardActions>
                    <Button 
                      size="small" 
                      startIcon={<EditIcon />}
                      component={RouterLink} 
                      to={`/design?id=${experiment.id}`}
                    >
                      Edit
                    </Button>
                    <Button 
                      size="small" 
                      startIcon={<PlayArrowIcon />} 
                      color="primary"
                      component={RouterLink} 
                      to={`/run/${experiment.id}`}
                    >
                      Run
                    </Button>
                  </CardActions>
                </Card>
              </Grid>
            ))}
          </Grid>
        )}
      </Box>

      {/* New Experiment Dialog */}
      <Dialog open={openNewDialog} onClose={() => setOpenNewDialog(false)}>
        <DialogTitle>Create New Experiment</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            id="name"
            label="Experiment Name"
            type="text"
            fullWidth
            variant="outlined"
            value={newExperimentName}
            onChange={(e) => setNewExperimentName(e.target.value)}
          />
          <TextField
            margin="dense"
            id="description"
            label="Description"
            type="text"
            fullWidth
            variant="outlined"
            multiline
            rows={4}
            value={newExperimentDesc}
            onChange={(e) => setNewExperimentDesc(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpenNewDialog(false)}>Cancel</Button>
          <Button 
            onClick={handleCreateNewExperiment}
            disabled={!newExperimentName.trim()}
            variant="contained"
          >
            Create
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
};

export default Home; 