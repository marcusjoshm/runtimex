#!/bin/bash

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "Python 3 is not installed. Please install it before running this script."
    exit 1
fi

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo "Node.js is not installed. Please install it before running this script."
    exit 1
fi

# Check if the required directories exist
if [ ! -d "backend" ] || [ ! -d "frontend" ]; then
    echo "Error: Could not find backend or frontend directories."
    echo "Make sure you're running this script from the project root directory."
    exit 1
fi

# Start the backend server
echo "Starting the backend server..."
cd backend
pip3 install -r requirements.txt > /dev/null 2>&1 # Install dependencies if needed
python3 main.py &
BACKEND_PID=$!
cd ..

# Give the backend a moment to start up
sleep 2

# Start the frontend development server
echo "Starting the frontend development server..."
cd frontend
npm install > /dev/null 2>&1 # Install dependencies if needed
npm start &
FRONTEND_PID=$!

# Function to handle script termination
cleanup() {
    echo "Shutting down servers..."
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    exit 0
}

# Set up trap for clean shutdown
trap cleanup SIGINT SIGTERM

echo
echo "runtimex is running!"
echo "Backend API: http://localhost:5001/api"
echo "Frontend Web App: http://localhost:3000"
echo
echo "Press Ctrl+C to stop both servers"
echo

# Wait for user to terminate
wait 