# runtimex

A flexible scheduling application for managing complex, multi-step processes like lab experiments or training routines. runtimex helps manage timing conflicts between different steps and resources, allowing users to efficiently multitask during time-sensitive activities. Under construction..

## About the Name

runtimex is a play on "runtime" (the execution time of a program) and "Timex" (the classic watch brand). As a former running, I always wore a Timex watch. I used it for everything. It worked perfectly fine: a clock, a stopwatch with laps, a timer, an alarm. Now I need something more. runtimex is the last timer you'll ever need.

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

## Prerequisites

- **Python 3.11+** (tested with Python 3.13)
- **Node.js 18+** (tested with Node.js 24.3.0)
- **Git** for cloning the repository

## Getting Started

### Quick Start (Recommended)

The easiest way to get runtimex running is to use the provided startup script:

```bash
# Clone the repository
git clone <your-repo-url>
cd runtimex

# Run the startup script (installs dependencies and starts both servers)
./start.sh
```

This will:
- Set up a Python virtual environment
- Install all backend dependencies
- Install all frontend dependencies  
- Start both servers simultaneously

### Manual Setup

If you prefer to set up manually or need to troubleshoot:

#### 1. Backend Setup

```bash
# Create and activate virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install Python dependencies
pip install -r backend/requirements.txt

# Start the backend server
cd backend
python main.py
```
This will start the API server on **port 5001** and run a test experiment.

#### 2. Frontend Setup

```bash
# Install Node.js dependencies
cd frontend
npm install

# Start the development server
npm start
```
This will start the React development server on **port 3000**.

### Environment Setup Notes

- **Virtual Environment**: We recommend using a virtual environment to avoid Python package conflicts
- **Port 5001**: The backend uses port 5001 instead of 5000 to avoid conflicts with macOS AirTunes service
- **Dependencies**: All packages are pinned to versions compatible with Python 3.13

## How to Use

### Application URLs

- **Frontend Web App**: http://localhost:3000
- **Backend API**: http://localhost:5001/api

### Getting Started

1. Open the web app at http://localhost:3000
2. Register for an account or login if you already have one
3. Create a new experiment by clicking the "New Experiment" button on the Home page
4. Design your experiment by adding steps in the ExperimentDesigner:
   - Choose step types (Fixed Duration, Task, Fixed Start, Automated Task)
   - Set durations and dependencies
   - Assign resources to prevent conflicts
5. When ready to run your experiment, click the "Run" button
6. Use the ExperimentRunner interface to control the experiment:
   - Start steps when you're ready
   - Monitor progress with visual timers and progress bars
   - See upcoming steps and handle conflicts
   - Pause/resume user-driven tasks
   - Mark steps as completed when done
7. For smartwatches or mobile devices, use the Watch View at `/watch/{experimentId}`
8. Share experiments with colleagues by clicking the share button
9. Export experiments to JSON files or save them as templates for future use
10. Stay informed with the real-time notification system for step updates and required actions

### Key Features

- **Real-time updates**: Changes sync automatically between browser tabs and devices
- **Resource management**: Prevent conflicts when multiple steps need the same equipment
- **Flexible step types**: Support for different timing requirements (fixed timers, user tasks, etc.)
- **Dependency management**: Steps can depend on completion of other steps
- **Import/Export**: Share experiment protocols as JSON files
- **Templates**: Save frequently used experiment designs

## Troubleshooting

### Common Issues

**Backend won't start - "ModuleNotFoundError"**
- Make sure you've activated the virtual environment: `source venv/bin/activate`
- Install dependencies: `pip install -r backend/requirements.txt`

**Frontend won't start - "command not found: npm"**
- Install Node.js: `brew install node` (macOS) or download from nodejs.org
- Verify installation: `node --version && npm --version`

**Port 5001 already in use**
- Check what's using the port: `lsof -i :5001`
- Kill the process or change the port in `backend/main.py`

**Virtual environment issues**
- Delete and recreate: `rm -rf venv && python3 -m venv venv`
- Use the correct Python version: `python3 --version` (should be 3.11+)

**Real-time updates not working**
- Check browser console for WebSocket connection errors
- Ensure both frontend and backend are running
- Try refreshing the page

### Development Notes

- Always activate the virtual environment before running Python commands
- The backend includes a test experiment that runs automatically on startup
- Both servers support hot reloading during development
- Use the browser's developer tools to inspect API calls and WebSocket connections

## Current Status

- [x] ✅ **FULLY FUNCTIONAL**: Complete development environment setup
- [x] ✅ **BACKEND**: Core scheduling logic with dependency management  
- [x] ✅ **API**: Comprehensive REST API for all operations
- [x] ✅ **FRONTEND**: Modern React/TypeScript interface with Material-UI
- [x] ✅ **REAL-TIME**: WebSocket integration for live updates
- [x] ✅ **AUTHENTICATION**: User registration, login, and session management
- [x] ✅ **COLLABORATION**: Experiment sharing with permissions
- [x] ✅ **DATA MANAGEMENT**: Import/export and template system
- [x] ✅ **NOTIFICATIONS**: Comprehensive alert system
- [x] ✅ **MOBILE/WATCH**: Optimized interface for small screens
- [x] ✅ **RESOURCE MANAGEMENT**: Conflict detection and prevention
- [x] ✅ **MULTIPLE STEP TYPES**: Support for various timing requirements

## Future Enhancements

The core functionality is complete and fully working! Future development could include:

### Advanced Features
- **Branching workflows**: Conditional steps based on experiment outcomes
- **Advanced analytics**: Detailed reports on experiment timing and efficiency
- **Calendar integration**: Schedule experiments in advance
- **Equipment APIs**: Direct integration with lab equipment and IoT devices

### Export & Integration
- **PDF reports**: Generate formatted experiment protocols and results
- **CSV exports**: Data analysis in Excel/Sheets
- **Third-party integrations**: LIMS, lab notebooks, project management tools

### Mobile & Deployment
- **Native mobile app**: iOS/Android with offline capabilities
- **Database backend**: PostgreSQL/MySQL for production deployment
- **Cloud hosting**: Docker containers with cloud deployment guides
- **Multi-tenant**: Support for multiple organizations

### Advanced Collaboration
- **Team workspaces**: Organization-level experiment libraries
- **Version control**: Track changes to experiment protocols
- **Comment system**: Collaborative notes and discussions
- **Approval workflows**: Quality control for critical experiments

### Performance & Scale
- **Performance optimization**: Handle hundreds of concurrent experiments
- **Advanced scheduling**: AI-powered optimal scheduling suggestions
- **Batch operations**: Run multiple experiments simultaneously
- **Historical analysis**: Learn from past experiments to improve future ones

---

**The application is production-ready for individual and small team use!** 🚀
