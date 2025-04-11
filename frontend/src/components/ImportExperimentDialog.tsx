import React, { useState, useRef } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Typography,
  Box,
  Alert,
  LinearProgress
} from '@mui/material';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import apiClient from '../api/client';

interface ImportExperimentDialogProps {
  open: boolean;
  onClose: () => void;
  onImportSuccess: () => void;
}

const ImportExperimentDialog: React.FC<ImportExperimentDialogProps> = ({
  open,
  onClose,
  onImportSuccess
}) => {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (event.target.files && event.target.files.length > 0) {
      const file = event.target.files[0];
      
      // Check if file is JSON
      if (!file.name.endsWith('.json')) {
        setError('Only JSON files are supported');
        setSelectedFile(null);
        return;
      }
      
      setSelectedFile(file);
      setError(null);
    }
  };

  const handleImport = async () => {
    if (!selectedFile) {
      setError('Please select a file to import');
      return;
    }
    
    try {
      setLoading(true);
      setError(null);
      
      await apiClient.importExperiment(selectedFile);
      onImportSuccess();
      onClose();
    } catch (err: any) {
      setError(err.response?.data?.error || 'Failed to import experiment. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleBrowseClick = () => {
    fileInputRef.current?.click();
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Import Experiment</DialogTitle>
      <DialogContent>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}
        
        <Box sx={{ 
          border: '2px dashed #ccc',
          borderRadius: 2,
          p: 3,
          textAlign: 'center',
          my: 2
        }}>
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileSelect}
            accept=".json"
            style={{ display: 'none' }}
          />
          
          <UploadFileIcon sx={{ fontSize: 48, color: 'primary.main', mb: 2 }} />
          
          <Typography variant="h6" gutterBottom>
            Select Experiment File
          </Typography>
          
          <Typography variant="body2" color="text.secondary" gutterBottom>
            Supported format: .json
          </Typography>
          
          {selectedFile ? (
            <Typography variant="body1" sx={{ mt: 2 }}>
              Selected: {selectedFile.name}
            </Typography>
          ) : (
            <Button 
              variant="outlined" 
              onClick={handleBrowseClick} 
              sx={{ mt: 2 }}
            >
              Browse Files
            </Button>
          )}
        </Box>
        
        {loading && <LinearProgress sx={{ mt: 2 }} />}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button 
          onClick={handleImport} 
          variant="contained" 
          disabled={!selectedFile || loading}
        >
          Import
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default ImportExperimentDialog; 