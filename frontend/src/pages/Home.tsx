import React, { useState, useEffect, useCallback } from 'react';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import { 
  Box, 
  Button, 
  Card, 
  CardContent, 
  CardActions, 
  Container, 
  Grid, 
  Typography,
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
import WatchIcon from '@mui/icons-material/Watch';
import ShareIcon from '@mui/icons-material/Share';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import CloudDownloadIcon from '@mui/icons-material/CloudDownload';
import BookmarkIcon from '@mui/icons-material/Bookmark';
import apiClient, { Experiment } from '../api/client';
import ShareExperimentDialog from '../components/ShareExperimentDialog';
import authClient, { User } from '../api/auth';
import ImportExperimentDialog from '../components/ImportExperimentDialog';
import TemplatesDialog from '../components/TemplatesDialog';

const Home: React.FC = () => {
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openNewDialog, setOpenNewDialog] = useState(false);
  const [newExperimentName, setNewExperimentName] = useState('');
  const [newExperimentDesc, setNewExperimentDesc] = useState('');
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [shareDialogOpen, setShareDialogOpen] = useState(false);
  const [shareExperimentId, setShareExperimentId] = useState('');
  const [shareExperimentName, setShareExperimentName] = useState('');
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [templatesDialogOpen, setTemplatesDialogOpen] = useState(false);
  const navigate = useNavigate();

  // Function to fetch experiments from API
  const fetchExperiments = useCallback(async () => {
    setLoading(true);
    
    try {
      // If user is logged in, get their experiments. Otherwise, get all experiments.
      const data = currentUser 
        ? await apiClient.getUserExperiments()
        : await apiClient.getExperiments();
      
      setExperiments(data);
      setError(null);
    } catch (err) {
      console.error('Failed to fetch experiments:', err);
      setError('Failed to load experiments. Please try again later.');
    } finally {
      setLoading(false);
    }
  }, [currentUser]);

  // Load experiments from API
  useEffect(() => {
    fetchExperiments();
  }, [fetchExperiments]);

  // Check auth state on load
  useEffect(() => {
    const checkAuth = async () => {
      const user = await authClient.getCurrentUser();
      setCurrentUser(user);
    };
    
    checkAuth();
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

  // Add function to handle share button click
  const handleShareClick = (experiment: Experiment) => {
    setShareExperimentId(experiment.id);
    setShareExperimentName(experiment.name);
    setShareDialogOpen(true);
  };

  // Add handler for export
  const handleExportExperiment = (experimentId: string) => {
    apiClient.exportExperiment(experimentId);
  };

  // Add handler for template creation
  const handleCreateTemplate = async (experimentId: string, experimentName: string) => {
    try {
      const templateName = window.prompt('Enter a name for this template:', experimentName);
      if (!templateName) return; // User cancelled
      
      await apiClient.createTemplate(experimentId, templateName);
      alert('Template created successfully!');
    } catch (err: any) {
      console.error('Failed to create template:', err);
      alert('Failed to create template. Please try again.');
    }
  };

  return (
    <Container maxWidth="lg">
      <Box sx={{ my: 4 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
          <Typography variant="h4" component="h1" gutterBottom>
            My Experiments
          </Typography>
          <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 3 }}>
            {currentUser && (
              <>
                <Button
                  variant="outlined"
                  startIcon={<CloudUploadIcon />}
                  onClick={() => setImportDialogOpen(true)}
                  sx={{ mr: 2 }}
                >
                  Import
                </Button>
                <Button
                  variant="outlined"
                  startIcon={<BookmarkIcon />}
                  onClick={() => setTemplatesDialogOpen(true)}
                  sx={{ mr: 2 }}
                >
                  Templates
                </Button>
              </>
            )}
            <Button
              variant="contained"
              startIcon={<AddIcon />}
              onClick={() => navigate('/design')}
            >
              New Experiment
            </Button>
          </Box>
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
                    {currentUser && experiment.owner === currentUser.username && (
                      <Button
                        size="small"
                        color="secondary"
                        onClick={() => handleShareClick(experiment)}
                        startIcon={<ShareIcon />}
                      >
                        Share
                      </Button>
                    )}
                    {currentUser && experiment.owner === currentUser.username && (
                      <Button
                        size="small"
                        onClick={() => handleExportExperiment(experiment.id)}
                        startIcon={<CloudDownloadIcon />}
                      >
                        Export
                      </Button>
                    )}
                    {currentUser && experiment.owner === currentUser.username && (
                      <Button
                        size="small"
                        onClick={() => handleCreateTemplate(experiment.id, experiment.name)}
                        startIcon={<BookmarkIcon />}
                      >
                        Save as Template
                      </Button>
                    )}
                    <Button
                      size="small"
                      color="secondary"
                      onClick={() => navigate(`/watch/${experiment.id}`)}
                      startIcon={<WatchIcon />}
                    >
                      Watch View
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

      {/* Share Experiment Dialog */}
      {shareDialogOpen && (
        <ShareExperimentDialog
          open={shareDialogOpen}
          onClose={() => setShareDialogOpen(false)}
          experimentId={shareExperimentId}
          experimentName={shareExperimentName}
        />
      )}

      {importDialogOpen && (
        <ImportExperimentDialog
          open={importDialogOpen}
          onClose={() => setImportDialogOpen(false)}
          onImportSuccess={fetchExperiments}
        />
      )}

      {templatesDialogOpen && (
        <TemplatesDialog
          open={templatesDialogOpen}
          onClose={() => setTemplatesDialogOpen(false)}
          onTemplateSelected={(experiment) => {
            fetchExperiments();
            navigate(`/design?id=${experiment.id}`);
          }}
        />
      )}
    </Container>
  );
};

export default Home; 