import React from 'react';
import { Link as RouterLink } from 'react-router-dom';
import AppBar from '@mui/material/AppBar';
import Toolbar from '@mui/material/Toolbar';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import AlarmIcon from '@mui/icons-material/Alarm';
import { Box } from '@mui/material';

const AppHeader: React.FC = () => {
  return (
    <AppBar position="static">
      <Toolbar>
        <Box sx={{ display: 'flex', alignItems: 'center' }}>
          <AlarmIcon sx={{ mr: 1 }} />
          <Typography variant="h6" component="div" sx={{ flexGrow: 1 }}>
            runtimex
          </Typography>
        </Box>
        <Box sx={{ flexGrow: 1 }} />
        <Button color="inherit" component={RouterLink} to="/">
          Home
        </Button>
        <Button color="inherit" component={RouterLink} to="/design">
          Design Experiment
        </Button>
      </Toolbar>
    </AppBar>
  );
};

export default AppHeader; 