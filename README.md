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

## Project Structure

*   `backend/`: Core scheduling logic and API (Python/Flask or FastAPI).
    - `models.py`: Defines the data structures for Experiments and Steps
    - `scheduler.py`: Manages scheduling, dependencies, and conflicts
    - `main.py`: API endpoints and test code
*   `frontend/`: Web interface (React/TypeScript with Material UI).
    - `src/pages/`: Main application pages
      - `Home.tsx`: Experiment list and creation
      - `ExperimentDesigner.tsx`: Interface for designing experiment steps
      - `ExperimentRunner.tsx`: Timer interface for running experiments
    - `src/components/`: Reusable UI components
    - `src/api/`: API client for communicating with backend
*   `mobile/`: (Future) Mobile app for controlling experiments remotely

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
2. Create a new experiment by clicking the "+" button on the Home page
3. Design your experiment by adding steps in the ExperimentDesigner
4. When ready to run your experiment, click the "Run" button
5. Use the ExperimentRunner interface to control the experiment:
   - Start steps when you're ready
   - Monitor progress with visual timers
   - See upcoming steps and handle conflicts
   - Mark steps as completed when done

## Current Status

- [x] Core scheduling logic in the backend
- [x] REST API for experiment operations
- [x] Basic React frontend structure
- [x] Home page with experiment list
- [x] Experiment designer interface
- [x] Experiment runner interface
- [ ] Real-time updates between frontend and backend
- [ ] Mobile/watch companion app
- [ ] User authentication and sharing
- [ ] Export/import experiments
- [ ] Notifications and alerts

## Planned Features

- Multiple experiment templates
- More sophisticated resource conflict detection and resolution
- Real-time notifications
- Reports and analytics
- Export to PDF/CSV
- Authentication and sharing capabilities
