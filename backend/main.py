from datetime import datetime, timedelta
import time # For simulating delays (optional)
import json
import os
from flask import Flask, jsonify, request
from flask_cors import CORS

from models import Experiment, Step, StepStatus, StepType
from scheduler import Scheduler

app = Flask(__name__)
CORS(app)

# Global scheduler instance to maintain state
scheduler = Scheduler()

# --- Define Helper Function to Print Schedule --- 
def print_schedule(scheduler: Scheduler):
    print("\n--- Current Schedule ---")
    # Sort steps by scheduled start time for readability
    sorted_steps = sorted(
        scheduler.schedule.values(),
        key=lambda s: s.scheduled_start_time or datetime.max
    )
    for step in sorted_steps:
        start = step.scheduled_start_time.strftime("%H:%M:%S") if step.scheduled_start_time else "Not Scheduled"
        end = step.scheduled_end_time.strftime("%H:%M:%S") if step.scheduled_end_time else "Not Scheduled"
        actual_start = step.actual_start_time.strftime("%H:%M:%S") if step.actual_start_time else "N/A"
        actual_end = step.actual_end_time.strftime("%H:%M:%S") if step.actual_end_time else "N/A"
        print(
            f"- {step.name:<20} | Status: {step.status.value:<10} | Type: {step.step_type.value:<15} | Scheduled: {start} - {end} | Actual: {actual_start} - {actual_end}"
        )
    print("------------------------\n")

# Helper function to convert experiment object to JSON-serializable dict
def experiment_to_dict(experiment):
    steps = []
    for step_id, step in experiment.steps.items():
        step_dict = {
            'id': step.id,
            'name': step.name,
            'type': step.step_type.value,
            'duration': step.duration.total_seconds() // 60,  # Convert to minutes
            'status': step.status.value,
            'dependencies': step.dependencies,
            'notes': step.notes,
            'resourceNeeded': step.resource_needed,
        }
        
        # Add timing information
        if step.scheduled_start_time:
            step_dict['scheduledStartTime'] = step.scheduled_start_time.isoformat()
        if step.scheduled_end_time:
            step_dict['scheduledEndTime'] = step.scheduled_end_time.isoformat()
        if step.actual_start_time:
            step_dict['actualStartTime'] = step.actual_start_time.isoformat()
        if step.actual_end_time:
            step_dict['actualEndTime'] = step.actual_end_time.isoformat()
        if step.elapsed_time:
            step_dict['elapsedTime'] = step.elapsed_time.total_seconds()
            
        steps.append(step_dict)
        
    return {
        'id': experiment.id,
        'name': experiment.name,
        'description': experiment.description,
        'steps': steps
    }

# --- API Routes ---

@app.route('/api/experiments', methods=['GET'])
def get_experiments():
    # Return all experiments
    experiments = [experiment_to_dict(exp) for exp in scheduler.experiments.values()]
    return jsonify(experiments)

@app.route('/api/experiments/<experiment_id>', methods=['GET'])
def get_experiment(experiment_id):
    # Return a specific experiment
    experiment = scheduler.experiments.get(experiment_id)
    if not experiment:
        return jsonify({'error': 'Experiment not found'}), 404
    
    return jsonify(experiment_to_dict(experiment))

@app.route('/api/experiments', methods=['POST'])
def create_experiment():
    # Create a new experiment
    data = request.json
    
    experiment = Experiment(
        name=data['name'],
        description=data.get('description', '')
    )
    
    for step_data in data.get('steps', []):
        duration_minutes = int(step_data.get('duration', 0))
        step = Step(
            name=step_data['name'],
            duration=timedelta(minutes=duration_minutes),
            step_type=StepType(step_data.get('type', 'fixed_duration')),
            dependencies=step_data.get('dependencies', []),
            notes=step_data.get('notes'),
            resource_needed=step_data.get('resourceNeeded')
        )
        experiment.add_step(step)
    
    scheduler.add_experiment(experiment)
    
    if experiment.steps:
        start_time = datetime.now()
        scheduler.calculate_initial_schedule(start_time=start_time)
    
    return jsonify(experiment_to_dict(experiment)), 201

@app.route('/api/experiments/<experiment_id>', methods=['PUT'])
def update_experiment(experiment_id):
    # Update an existing experiment
    experiment = scheduler.experiments.get(experiment_id)
    if not experiment:
        return jsonify({'error': 'Experiment not found'}), 404
    
    data = request.json
    
    # Update basic info
    experiment.name = data.get('name', experiment.name)
    experiment.description = data.get('description', experiment.description)
    
    # For a real app, we'd need a more sophisticated way to sync steps
    # This is simplistic - it removes all existing steps and adds new ones
    if 'steps' in data:
        experiment.steps = {}  # Clear existing steps
        
        for step_data in data['steps']:
            duration_minutes = int(step_data.get('duration', 0))
            step = Step(
                name=step_data['name'],
                duration=timedelta(minutes=duration_minutes),
                step_type=StepType(step_data.get('type', 'fixed_duration')),
                dependencies=step_data.get('dependencies', []),
                notes=step_data.get('notes'),
                resource_needed=step_data.get('resourceNeeded')
            )
            experiment.add_step(step)
        
        # Recalculate schedule
        start_time = datetime.now()
        scheduler.calculate_initial_schedule(start_time=start_time)
    
    return jsonify(experiment_to_dict(experiment))

@app.route('/api/steps/<step_id>/start', methods=['POST'])
def start_step(step_id):
    # Start a step
    step = scheduler.get_step(step_id)
    if not step:
        return jsonify({'error': 'Step not found'}), 404
    
    scheduler.handle_step_start(step_id)
    experiment = None
    
    # Find the experiment this step belongs to
    for exp in scheduler.experiments.values():
        if step_id in exp.steps:
            experiment = exp
            break
    
    if experiment:
        return jsonify(experiment_to_dict(experiment))
    else:
        return jsonify({'error': 'Experiment not found for step'}), 500

@app.route('/api/steps/<step_id>/pause', methods=['POST'])
def pause_step(step_id):
    # Pause a step
    step = scheduler.get_step(step_id)
    if not step:
        return jsonify({'error': 'Step not found'}), 404
    
    scheduler.handle_step_pause(step_id)
    
    # Find the experiment this step belongs to
    experiment = None
    for exp in scheduler.experiments.values():
        if step_id in exp.steps:
            experiment = exp
            break
    
    if experiment:
        return jsonify(experiment_to_dict(experiment))
    else:
        return jsonify({'error': 'Experiment not found for step'}), 500

@app.route('/api/steps/<step_id>/complete', methods=['POST'])
def complete_step(step_id):
    # Complete a step
    step = scheduler.get_step(step_id)
    if not step:
        return jsonify({'error': 'Step not found'}), 404
    
    scheduler.handle_step_complete(step_id)
    
    # Find the experiment this step belongs to
    experiment = None
    for exp in scheduler.experiments.values():
        if step_id in exp.steps:
            experiment = exp
            break
    
    if experiment:
        return jsonify(experiment_to_dict(experiment))
    else:
        return jsonify({'error': 'Experiment not found for step'}), 500

# --- Main Test Function --- 
def run_test():
    print("--- Starting Lab Timer Test Scenario ---")

    # 1. Create Steps for Dish 1
    pretreat = Step(
        name="Dish 1: Pretreat D1",
        duration=timedelta(minutes=30),
        step_type=StepType.FIXED_DURATION
    )
    treat = Step(
        name="Dish 1: Treat D2",
        duration=timedelta(minutes=60),
        step_type=StepType.FIXED_DURATION,
        dependencies=[pretreat.id]
    )
    wash = Step(
        name="Dish 1: Wash",
        duration=timedelta(minutes=4),
        step_type=StepType.TASK, # Pausable task
        dependencies=[treat.id]
    )
    recover = Step(
        name="Dish 1: Recover",
        duration=timedelta(minutes=60),
        step_type=StepType.FIXED_START,
        dependencies=[wash.id]
    )
    image_setup = Step(
        name="Dish 1: Setup Imaging",
        duration=timedelta(minutes=5),
        step_type=StepType.TASK,
        dependencies=[recover.id],
        resource_needed='user_attention'
    )
    image_capture = Step(
        name="Dish 1: Image Capture",
        duration=timedelta(minutes=20),
        step_type=StepType.AUTOMATED_TASK,
        dependencies=[image_setup.id],
        resource_needed='microscope'
    )

    # 2. Create Experiment and Add Steps
    experiment_d1 = Experiment(name="Dish 1 Processing")
    experiment_d1.add_step(pretreat)
    experiment_d1.add_step(treat)
    experiment_d1.add_step(wash)
    experiment_d1.add_step(recover)
    experiment_d1.add_step(image_setup)
    experiment_d1.add_step(image_capture)

    # 3. Add Experiment to Scheduler
    scheduler.add_experiment(experiment_d1)

    # 4. Calculate Initial Schedule (starting now)
    start_time = datetime.now()
    print(f"\nCalculating initial schedule starting around: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    scheduler.calculate_initial_schedule(start_time=start_time)

    # 5. Print Initial Schedule
    print_schedule(scheduler)

    # 6. Simulate Running the First Step
    print("--- Simulating Experiment Execution ---")

    # Find the first ready step
    first_step_id = None
    for step_id, step in scheduler.schedule.items():
        if step.status == StepStatus.READY:
            first_step_id = step_id
            print(f"Found ready step: {step.name}")
            break

    if not first_step_id:
        print("Error: No step found in READY state after initial scheduling.")
        return

    # Start the first step
    print(f"\nStarting step: {scheduler.get_step(first_step_id).name}")
    start_event_time = datetime.now() # Simulate user pressing start
    scheduler.handle_step_start(first_step_id, start_time=start_event_time)
    print_schedule(scheduler)

    # Simulate time passing until the first step is done
    # For this test, we'll just complete it immediately after starting
    # In reality, this would happen after pretreat.duration has passed
    print(f"Simulating completion of step: {scheduler.get_step(first_step_id).name}")
    # We use the original start time + duration to simulate ideal completion
    completion_time = start_event_time + pretreat.duration
    scheduler.handle_step_complete(first_step_id, end_time=completion_time)

    # 7. Print Schedule Again to See Status Updates
    print("\n--- Schedule after completing first step ---")
    print_schedule(scheduler)

    print("--- Test Scenario Complete ---")

if __name__ == "__main__":
    # If run directly, run the test scenario
    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        run_test()
    
    # Start the Flask app
    app.run(debug=True, port=5000)
