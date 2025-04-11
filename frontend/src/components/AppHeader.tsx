import React, { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  AppBar,
  Toolbar,
  Typography,
  Button,
  Box,
  Menu,
  MenuItem,
  IconButton,
  Avatar
} from '@mui/material';
import TimerIcon from '@mui/icons-material/Timer';
import authClient, { User } from '../api/auth';

const AppHeader: React.FC = () => {
  const navigate = useNavigate();
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  
  useEffect(() => {
    const checkAuth = async () => {
      const user = await authClient.getCurrentUser();
      setCurrentUser(user);
    };
    
    checkAuth();
  }, []);
  
  const handleMenuOpen = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget);
  };
  
  const handleMenuClose = () => {
    setAnchorEl(null);
  };
  
  const handleLogout = () => {
    authClient.logout();
    setCurrentUser(null);
    handleMenuClose();
    navigate('/');
  };
  
  return (
    <AppBar position="static">
      <Toolbar>
        <TimerIcon sx={{ mr: 1 }} />
        <Typography variant="h6" component={Link} to="/" sx={{ flexGrow: 1, textDecoration: 'none', color: 'inherit' }}>
          runtimex
        </Typography>
        
        {currentUser ? (
          <>
            <IconButton 
              onClick={handleMenuOpen}
              size="small"
              aria-controls="user-menu"
              aria-haspopup="true"
              sx={{ ml: 2 }}
            >
              <Avatar sx={{ width: 32, height: 32, bgcolor: 'secondary.main' }}>
                {currentUser.username.charAt(0).toUpperCase()}
              </Avatar>
            </IconButton>
            <Menu
              id="user-menu"
              anchorEl={anchorEl}
              keepMounted
              open={Boolean(anchorEl)}
              onClose={handleMenuClose}
            >
              <MenuItem disabled>
                {currentUser.username}
              </MenuItem>
              <MenuItem onClick={handleLogout}>Logout</MenuItem>
            </Menu>
          </>
        ) : (
          <Box>
            <Button color="inherit" component={Link} to="/login">
              Login
            </Button>
            <Button color="inherit" component={Link} to="/register">
              Register
            </Button>
          </Box>
        )}
      </Toolbar>
    </AppBar>
  );
};

export default AppHeader; 