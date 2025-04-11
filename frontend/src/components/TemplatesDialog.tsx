import React, { useState, useEffect } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Typography,
  Box,
  List,
  ListItem,
  ListItemText,
  ListItemSecondaryAction,
  IconButton,
  TextField,
  Divider,
  Alert,
  CircularProgress
} from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import AddIcon from '@mui/icons-material/Add';
import apiClient from '../api/client';

interface TemplatesDialogProps {
  open: boolean;
  onClose: () => void;
  onTemplateSelected: (experimentData: any) => void;
}

const TemplatesDialog: React.FC<TemplatesDialogProps> = ({
  open,
  onClose,
  onTemplateSelected
}) => {
  const [templates, setTemplates] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newExperimentName, setNewExperimentName] = useState('');
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);

  // Fetch templates
  useEffect(() => {
    if (open) {
      fetchTemplates();
    }
  }, [open]);

  const fetchTemplates = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const data = await apiClient.getTemplates();
      setTemplates(data);
    } catch (err: any) {
      setError(err.response?.data?.error || 'Failed to load templates. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteTemplate = async (templateId: string, event: React.MouseEvent) => {
    event.stopPropagation();
    
    try {
      await apiClient.deleteTemplate(templateId);
      // Refresh the list
      fetchTemplates();
    } catch (err: any) {
      setError(err.response?.data?.error || 'Failed to delete template. Please try again.');
    }
  };

  const handleSelectTemplate = (templateId: string) => {
    setSelectedTemplateId(templateId);
    
    const selectedTemplate = templates.find(t => t.id === templateId);
    if (selectedTemplate) {
      setNewExperimentName(`${selectedTemplate.name} - Copy`);
    }
  };

  const handleCreateFromTemplate = async () => {
    if (!selectedTemplateId) {
      setError('Please select a template first');
      return;
    }
    
    try {
      const experiment = await apiClient.createFromTemplate(
        selectedTemplateId, 
        newExperimentName || undefined
      );
      
      onTemplateSelected(experiment);
      onClose();
    } catch (err: any) {
      setError(err.response?.data?.error || 'Failed to create experiment from template. Please try again.');
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Experiment Templates</DialogTitle>
      <DialogContent>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}
        
        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', my: 4 }}>
            <CircularProgress />
          </Box>
        ) : templates.length === 0 ? (
          <Box sx={{ textAlign: 'center', my: 4 }}>
            <Typography variant="body1">
              No templates available. Create a template from an existing experiment.
            </Typography>
          </Box>
        ) : (
          <>
            <List>
              {templates.map((template) => (
                <ListItem 
                  key={template.id}
                  button
                  selected={selectedTemplateId === template.id}
                  onClick={() => handleSelectTemplate(template.id)}
                >
                  <ListItemText
                    primary={template.name}
                    secondary={`Created: ${new Date(template.created_at).toLocaleDateString()}`}
                  />
                  <ListItemSecondaryAction>
                    <IconButton 
                      edge="end" 
                      onClick={(e) => handleDeleteTemplate(template.id, e)}
                    >
                      <DeleteIcon />
                    </IconButton>
                  </ListItemSecondaryAction>
                </ListItem>
              ))}
            </List>
            
            {selectedTemplateId && (
              <Box sx={{ mt: 3 }}>
                <Divider sx={{ mb: 2 }} />
                <Typography variant="h6" gutterBottom>
                  Create new experiment
                </Typography>
                <TextField
                  fullWidth
                  label="Experiment Name"
                  value={newExperimentName}
                  onChange={(e) => setNewExperimentName(e.target.value)}
                  margin="normal"
                />
              </Box>
            )}
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button 
          onClick={handleCreateFromTemplate} 
          variant="contained" 
          disabled={!selectedTemplateId || loading}
          startIcon={<AddIcon />}
        >
          Create Experiment
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default TemplatesDialog; 