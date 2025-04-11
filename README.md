# runtimex

A flexible scheduling application for managing complex, multi-step processes like lab experiments or training routines. runtimex helps manage timing conflicts between different steps and resources, allowing users to efficiently multitask during time-sensitive activities.

## About the Name

runtimex is a play on "runtime" (the execution time of a program) and "Timex" (the classic watch brand). As a former runner, this project aims to create the ideal timing tool I've always wanted - something that could manage complex, overlapping timing scenarios better than a traditional stopwatch.

## Features

*   Schedule multiple overlapping timers
*   Handle timing conflicts dynamically
*   Track elapsed time and adjust schedules based on actual start/stop times
*   Manage resource conflicts (equipment, user attention)
*   Web interface for detailed experiment design
*   Simple interface for controlling active experiments (intended for smartwatch/mobile)
*   User authentication and experiment sharing
*   Export/import experiments and save templates
*   Comprehensive notification system for alerts and interactive actions

## Project Structure

*   `backend/`: Core scheduling logic and API (Python/Flask or FastAPI).
    - `models.py`: Defines the data structures for Experiments and Steps
    - `scheduler.py`: Manages scheduling, dependencies, and conflicts
    - `main.py`: API endpoints and test code
    - `auth.py`: User authentication and authorization
    - `notifications.py`: Notification system and handlers
*   `frontend/`: Web interface (React/TypeScript with Material UI).
    - `src/pages/`: Main application pages
      - `Home.tsx`: Experiment list and creation
      - `ExperimentDesigner.tsx`: Interface for designing experiment steps
      - `ExperimentRunner.tsx`: Timer interface for running experiments
      - `WatchView.tsx`: Minimal interface optimized for smartwatches
      - `Login.tsx` & `Register.tsx`: User authentication pages
    - `src/components/`: Reusable UI components
      - `ImportExperimentDialog.tsx`: Dialog for importing experiments
      - `ShareExperimentDialog.tsx`: Dialog for sharing experiments
      - `TemplatesDialog.tsx`: Dialog for managing templates
      - `NotificationCenter.tsx`: Notification inbox and management
      - `NotificationToast.tsx`: Real-time notification alerts
    - `src/api/`: API client for communicating with backend
      - `client.ts`: API client for data operations
      - `auth.ts`: Authentication service
      - `socket.ts`: WebSocket service for real-time updates
      - `notifications.ts`: Client-side notification service

## Getting Started

### Backend Setup

1. Install Python dependencies:
   ```
   cd backend
   pip install -r requirements.txt
   ```

2. Run the backend server:
   ```
   python main.py
   ```
   This will start the API server on port 5000 and also run a test experiment.

### Frontend Setup

1. Install Node.js dependencies:
   ```
   cd frontend
   npm install
   ```

2. Start the development server:
   ```
   npm start
   ```
   This will start the React development server on port 3000.

## How to Use

1. Open the web app at http://localhost:3000
2. Register for an account or login if you already have one
3. Create a new experiment by clicking the "+" button on the Home page
4. Design your experiment by adding steps in the ExperimentDesigner
5. When ready to run your experiment, click the "Run" button
6. Use the ExperimentRunner interface to control the experiment:
   - Start steps when you're ready
   - Monitor progress with visual timers
   - See upcoming steps and handle conflicts
   - Mark steps as completed when done
7. For smartwatches or mobile devices, use the Watch View at `/watch/{experimentId}`
8. Share experiments with colleagues by clicking the share button
9. Export experiments to files or save them as templates for future use
10. Stay informed with the notification system for step updates and required actions

## Current Status

- [x] Core scheduling logic in the backend
- [x] REST API for experiment operations
- [x] Basic React frontend structure
- [x] Home page with experiment list
- [x] Experiment designer interface
- [x] Experiment runner interface
- [x] Real-time updates between frontend and backend
- [x] Mobile/watch companion app
- [x] User authentication and sharing
- [x] Export/import experiments
- [x] Notifications and alerts

## Future Enhancements

- Advanced experiment templates with branching workflows
- More sophisticated resource conflict detection and resolution
- Reports and analytics dashboard
- Export to PDF/CSV formats
- Mobile app with offline capabilities
- Integration with lab equipment via APIs
- Calendar integration
- Team collaboration features
