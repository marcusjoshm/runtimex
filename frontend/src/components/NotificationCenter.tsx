import React, { useState, useEffect } from 'react';
import {
  Badge,
  Drawer,
  IconButton,
  List,
  ListItem,
  ListItemText,
  Typography,
  Divider,
  Box,
  Tabs,
  Tab,
  Chip,
  Button,
  ButtonGroup,
  useTheme
} from '@mui/material';
import NotificationsIcon from '@mui/icons-material/Notifications';
import DeleteIcon from '@mui/icons-material/Delete';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import WarningIcon from '@mui/icons-material/Warning';
import InfoIcon from '@mui/icons-material/Info';
import ErrorIcon from '@mui/icons-material/Error';
import notificationService, { 
  Notification, 
  NotificationType,
  NotificationPriority
} from '../api/notifications';

interface NotificationCenterProps {
  onActionExecuted?: () => void;
}

const NotificationCenter: React.FC<NotificationCenterProps> = ({ onActionExecuted }) => {
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [tab, setTab] = useState(0);
  const theme = useTheme();

  useEffect(() => {
    const unsubscribe = notificationService.addListener((newNotifications) => {
      setNotifications(newNotifications);
    });
    
    return unsubscribe;
  }, []);

  const handleOpen = () => {
    setOpen(true);
    notificationService.fetchNotifications();
  };

  const handleClose = () => {
    setOpen(false);
  };

  const handleTabChange = (_event: React.SyntheticEvent, newValue: number) => {
    setTab(newValue);
  };

  const handleMarkAsRead = (notification: Notification) => {
    notificationService.markAsRead(notification.id);
  };

  const handleDismiss = (notification: Notification) => {
    notificationService.dismissNotification(notification.id);
  };

  const handleDelete = (notification: Notification) => {
    notificationService.deleteNotification(notification.id);
  };

  const handleAction = async (notification: Notification, actionId: string) => {
    const action = notification.actions.find(a => a.id === actionId);
    if (action) {
      await notificationService.executeAction(notification, action);
      if (onActionExecuted) {
        onActionExecuted();
      }
    }
  };

  const getNotificationIcon = (type: NotificationType, priority: NotificationPriority) => {
    switch (type) {
      case NotificationType.ERROR:
        return <ErrorIcon color="error" />;
      case NotificationType.RESOURCE_CONFLICT:
      case NotificationType.STEP_TIMEOUT:
        return <WarningIcon style={{ color: theme.palette.warning.main }} />;
      case NotificationType.USER_ATTENTION_REQUIRED:
        return <WarningIcon style={{ color: theme.palette.warning.main }} />;
      case NotificationType.STEP_COMPLETED:
        return <CheckCircleIcon color="success" />;
      default:
        return <InfoIcon color="info" />;
    }
  };

  const getPriorityColor = (priority: NotificationPriority) => {
    switch (priority) {
      case NotificationPriority.CRITICAL:
        return theme.palette.error.main;
      case NotificationPriority.HIGH:
        return theme.palette.warning.main;
      case NotificationPriority.MEDIUM:
        return theme.palette.info.main;
      case NotificationPriority.LOW:
      default:
        return theme.palette.success.main;
    }
  };

  // Filter notifications based on tab
  const filteredNotifications = notifications.filter(notification => {
    if (tab === 0) return !notification.is_dismissed;
    if (tab === 1) return notification.is_dismissed;
    return true;
  });

  return (
    <Drawer
      open={open}
      onClose={handleClose}
      PaperProps={{
        sx: {
          width: 350,
          padding: 2,
        },
      }}
    >
      <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        <Typography variant="h6" sx={{ padding: 2 }}>
          Notifications
        </Typography>
        <Divider />
        <Tabs
          value={tab}
          onChange={handleTabChange}
          variant="fullWidth"
          sx={{ flexGrow: 1 }}
        >
          <Tab label="Unread" />
          <Tab label="Dismissed" />
        </Tabs>
        <List>
          {filteredNotifications.map((notification) => (
            <ListItem key={notification.id}>
              <IconButton onClick={() => handleMarkAsRead(notification)}>
                {getNotificationIcon(notification.type, notification.priority)}
              </IconButton>
              <ListItemText
                primary={notification.title}
                secondary={notification.message}
              />
              <IconButton onClick={() => handleDismiss(notification)}>
                <DeleteIcon />
              </IconButton>
            </ListItem>
          ))}
        </List>
        <Divider />
        <Box sx={{ padding: 2, display: 'flex', justifyContent: 'space-between' }}>
          <Button onClick={handleClose}>Close</Button>
          <Button onClick={handleOpen}>Refresh</Button>
        </Box>
      </Box>
    </Drawer>
  );
};

export default NotificationCenter; 