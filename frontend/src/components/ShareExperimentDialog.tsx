import React, { useState } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Typography,
  Box,
  Alert
} from '@mui/material';
import apiClient from '../api/client';

interface ShareExperimentDialogProps {
  open: boolean;
  onClose: () => void;
  experimentId: string;
  experimentName: string;
}

const ShareExperimentDialog: React.FC<ShareExperimentDialogProps> = ({
  open,
  onClose,
  experimentId,
  experimentName
}) => {
  const [username, setUsername] = useState('');
  const [permission, setPermission] = useState<'view' | 'edit'>('view');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);

  const handleShare = async () => {
    if (!username.trim()) {
      setError('Username is required');
      return;
    }
    
    try {
      setLoading(true);
      setError(null);
      setSuccess(false);
      
      await apiClient.shareExperiment(experimentId, username, permission);
      setSuccess(true);
      setUsername('');
    } catch (err: any) {
      setError(err.response?.data?.error || 'Failed to share experiment. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Share "{experimentName}"</DialogTitle>
      <DialogContent>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}
        
        {success && (
          <Alert severity="success" sx={{ mb: 2 }}>
            Experiment shared successfully!
          </Alert>
        )}
        
        <Box sx={{ mt: 2 }}>
          <TextField
            fullWidth
            label="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            margin="normal"
            placeholder="Enter username to share with"
          />
          
          <FormControl fullWidth margin="normal">
            <InputLabel>Permission</InputLabel>
            <Select
              value={permission}
              label="Permission"
              onChange={(e) => setPermission(e.target.value as 'view' | 'edit')}
            >
              <MenuItem value="view">View only</MenuItem>
              <MenuItem value="edit">Edit</MenuItem>
            </Select>
          </FormControl>
          
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
            View only: User can see and run the experiment, but cannot modify it.<br />
            Edit: User can view, run, and modify the experiment.
          </Typography>
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button 
          onClick={handleShare} 
          variant="contained" 
          disabled={loading}
        >
          {loading ? 'Sharing...' : 'Share'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default ShareExperimentDialog; 