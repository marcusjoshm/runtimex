from datetime import datetime, timedelta
import time # For simulating delays (optional)
import json
import os
import tempfile
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from flask_socketio import SocketIO, join_room, leave_room
from flask_jwt_extended import JWTManager, jwt_required, get_jwt_identity
import uuid

from models import Experiment, Step, StepStatus, StepType
from scheduler import Scheduler
import auth

# Import notification system
from notifications import NotificationService, Notification, NotificationType, NotificationPriority, ActionType, NotificationAction, create_notification_factories

app = Flask(__name__)
CORS(app)

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# Global scheduler instance to maintain state
scheduler = Scheduler()

# Add after app creation
app.config["JWT_SECRET_KEY"] = "your-secret-key-change-in-production"
jwt = JWTManager(app)

# Initialize auth routes and get the user getter function
get_user = auth.register_auth_routes(app, jwt)

# Update the scheduler to track experiment ownership
scheduler.user_experiments = {}  # username -> [experiment_ids]

# Initialize notification service with socketio
notification_service = NotificationService(socketio)

# Create notification factories
notification_factories = create_notification_factories(scheduler)

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
        
    result = {
        'id': experiment.id,
        'name': experiment.name,
        'description': experiment.description,
        'steps': steps
    }
    
    # Add ownership information if available
    if hasattr(experiment, 'owner'):
        result['owner'] = experiment.owner
        result['sharedWith'] = experiment.shared_with
    
    return result

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
@jwt_required()
def create_experiment():
    # Create a new experiment
    data = request.json
    username = get_jwt_identity()
    
    experiment = Experiment(
        name=data['name'],
        description=data.get('description', '')
    )
    
    # Add ownership information
    experiment.owner = username
    experiment.shared_with = {}  # username -> permission
    
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
    
    # Track experiment ownership
    if username not in scheduler.user_experiments:
        scheduler.user_experiments[username] = []
    scheduler.user_experiments[username].append(experiment.id)
    
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

# Add a route to get user's experiments
@app.route('/api/user/experiments', methods=['GET'])
@jwt_required()
def get_user_experiments():
    username = get_jwt_identity()
    
    # Get experiments owned by user
    user_experiment_ids = scheduler.user_experiments.get(username, [])
    experiments = []
    
    for exp_id in user_experiment_ids:
        if exp_id in scheduler.experiments:
            experiments.append(experiment_to_dict(scheduler.experiments[exp_id]))
    
    # Get experiments shared with user
    user = get_user(username)
    if user:
        for exp_id in user.shared_experiments:
            if exp_id in scheduler.experiments:
                experiments.append(experiment_to_dict(scheduler.experiments[exp_id]))
    
    return jsonify(experiments)

# Add route to share an experiment
@app.route('/api/experiments/<experiment_id>/share', methods=['POST'])
@jwt_required()
def share_experiment(experiment_id):
    username = get_jwt_identity()
    data = request.json
    share_with_username = data.get('username')
    permission = data.get('permission', 'view')  # 'view' or 'edit'
    
    # Validate input
    if not share_with_username:
        return jsonify({"error": "Username to share with is required"}), 400
    
    if permission not in ['view', 'edit']:
        return jsonify({"error": "Permission must be 'view' or 'edit'"}), 400
    
    # Get experiment
    experiment = scheduler.experiments.get(experiment_id)
    if not experiment:
        return jsonify({"error": "Experiment not found"}), 404
    
    # Check if user is the owner
    if getattr(experiment, 'owner', None) != username:
        return jsonify({"error": "Only the owner can share this experiment"}), 403
    
    # Get user to share with
    share_with_user = get_user(share_with_username)
    if not share_with_user:
        return jsonify({"error": "User to share with not found"}), 404
    
    # Share the experiment
    experiment.shared_with[share_with_username] = permission
    share_with_user.shared_experiments[experiment_id] = permission
    
    return jsonify({"message": f"Experiment shared with {share_with_username}"}), 200

# Add export experiment endpoint
@app.route('/api/experiments/<experiment_id>/export', methods=['GET'])
@jwt_required(optional=True)  # Make auth optional so non-logged-in users can still export
def export_experiment(experiment_id):
    # Get experiment
    experiment = scheduler.experiments.get(experiment_id)
    if not experiment:
        return jsonify({"error": "Experiment not found"}), 404
    
    # Convert to exportable format (strip user-specific data)
    export_data = experiment_to_dict(experiment)
    
    # Remove owner and sharing info for privacy
    if 'owner' in export_data:
        del export_data['owner']
    if 'sharedWith' in export_data:
        del export_data['sharedWith']
    
    # Create a temporary file
    fd, path = tempfile.mkstemp(suffix='.json')
    try:
        with os.fdopen(fd, 'w') as tmp:
            json.dump(export_data, tmp, indent=2)
        
        # Return the file as an attachment
        return send_file(
            path,
            as_attachment=True,
            download_name=f"{experiment.name.replace(' ', '_')}_export.json",
            mimetype='application/json'
        )
    except Exception as e:
        return jsonify({"error": f"Export failed: {str(e)}"}), 500
    finally:
        # Ensure the temp file is removed after response
        try:
            os.remove(path)
        except:
            pass

# Add import experiment endpoint
@app.route('/api/experiments/import', methods=['POST'])
@jwt_required()
def import_experiment():
    username = get_jwt_identity()
    
    # Check if file was uploaded
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    if not file.filename.endswith('.json'):
        return jsonify({"error": "Only JSON files are supported"}), 400
    
    try:
        # Parse the file
        data = json.load(file)
        
        # Basic validation
        required_fields = ['name', 'steps']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Invalid experiment format: missing '{field}'"}), 400
        
        # Create a new experiment
        experiment = Experiment(
            name=data['name'],
            description=data.get('description', '')
        )
        
        # Add ownership information
        experiment.owner = username
        experiment.shared_with = {}
        
        # Add steps
        for step_data in data.get('steps', []):
            # Ensure step has required fields
            if 'name' not in step_data or 'type' not in step_data or 'duration' not in step_data:
                continue
            
            duration_minutes = int(step_data.get('duration', 0))
            step = Step(
                name=step_data['name'],
                duration=timedelta(minutes=duration_minutes),
                step_type=StepType(step_data.get('type', 'fixed_duration')),
                dependencies=step_data.get('dependencies', []),
                notes=step_data.get('notes', ''),
                resource_needed=step_data.get('resourceNeeded', '')
            )
            experiment.add_step(step)
        
        # Add to scheduler
        scheduler.add_experiment(experiment)
        
        # Track experiment ownership
        if username not in scheduler.user_experiments:
            scheduler.user_experiments[username] = []
        scheduler.user_experiments[username].append(experiment.id)
        
        # Calculate initial schedule
        if experiment.steps:
            start_time = datetime.now()
            scheduler.calculate_initial_schedule(start_time=start_time)
        
        return jsonify(experiment_to_dict(experiment)), 201
        
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON file"}), 400
    except Exception as e:
        return jsonify({"error": f"Import failed: {str(e)}"}), 500

# Add template management endpoints
@app.route('/api/templates', methods=['GET'])
@jwt_required()
def get_templates():
    username = get_jwt_identity()
    
    # In a real app, templates would be stored in a database
    # For now, we'll use a simple in-memory store
    if not hasattr(scheduler, 'templates'):
        scheduler.templates = {}
    
    # Get templates for the user
    user_templates = scheduler.templates.get(username, [])
    return jsonify(user_templates)

@app.route('/api/templates', methods=['POST'])
@jwt_required()
def create_template():
    username = get_jwt_identity()
    data = request.json
    
    # Validate input
    if 'experimentId' not in data or 'name' not in data:
        return jsonify({"error": "Experiment ID and template name are required"}), 400
    
    experiment_id = data['experimentId']
    template_name = data['name']
    
    # Get experiment
    experiment = scheduler.experiments.get(experiment_id)
    if not experiment:
        return jsonify({"error": "Experiment not found"}), 404
    
    # Check ownership (only owner can create templates)
    if getattr(experiment, 'owner', None) != username:
        return jsonify({"error": "Only the owner can create templates from this experiment"}), 403
    
    # Create template data (simplified experiment)
    template_data = {
        'id': str(uuid.uuid4()),
        'name': template_name,
        'source_experiment_id': experiment_id,
        'created_at': datetime.now().isoformat(),
        'steps': []
    }
    
    # Add steps (without status/timing info)
    for step_id, step in experiment.steps.items():
        template_data['steps'].append({
            'name': step.name,
            'type': step.step_type.value,
            'duration': step.duration.total_seconds() // 60,
            'dependencies': step.dependencies,
            'notes': step.notes,
            'resourceNeeded': step.resource_needed
        })
    
    # Store template
    if not hasattr(scheduler, 'templates'):
        scheduler.templates = {}
    
    if username not in scheduler.templates:
        scheduler.templates[username] = []
    
    scheduler.templates[username].append(template_data)
    
    return jsonify(template_data), 201

@app.route('/api/templates/<template_id>', methods=['DELETE'])
@jwt_required()
def delete_template(template_id):
    username = get_jwt_identity()
    
    # Check if templates exist
    if not hasattr(scheduler, 'templates') or username not in scheduler.templates:
        return jsonify({"error": "Template not found"}), 404
    
    # Find and remove template
    for i, template in enumerate(scheduler.templates[username]):
        if template['id'] == template_id:
            del scheduler.templates[username][i]
            return jsonify({"message": "Template deleted"}), 200
    
    return jsonify({"error": "Template not found"}), 404

@app.route('/api/experiments/create-from-template/<template_id>', methods=['POST'])
@jwt_required()
def create_from_template(template_id):
    username = get_jwt_identity()
    
    # Check if templates exist
    if not hasattr(scheduler, 'templates') or username not in scheduler.templates:
        return jsonify({"error": "Template not found"}), 404
    
    # Find template
    template = None
    for t in scheduler.templates[username]:
        if t['id'] == template_id:
            template = t
            break
    
    if not template:
        return jsonify({"error": "Template not found"}), 404
    
    # Get experiment name from request or use template name
    data = request.json or {}
    name = data.get('name', f"{template['name']} - Copy")
    
    # Create a new experiment
    experiment = Experiment(
        name=name,
        description=data.get('description', '')
    )
    
    # Add ownership information
    experiment.owner = username
    experiment.shared_with = {}
    
    # Add steps from template
    for step_data in template['steps']:
        duration_minutes = int(step_data.get('duration', 0))
        step = Step(
            name=step_data['name'],
            duration=timedelta(minutes=duration_minutes),
            step_type=StepType(step_data.get('type', 'fixed_duration')),
            dependencies=step_data.get('dependencies', []),
            notes=step_data.get('notes', ''),
            resource_needed=step_data.get('resourceNeeded', '')
        )
        experiment.add_step(step)
    
    # Add to scheduler
    scheduler.add_experiment(experiment)
    
    # Track experiment ownership
    if username not in scheduler.user_experiments:
        scheduler.user_experiments[username] = []
    scheduler.user_experiments[username].append(experiment.id)
    
    # Calculate initial schedule
    if experiment.steps:
        start_time = datetime.now()
        scheduler.calculate_initial_schedule(start_time=start_time)
    
    return jsonify(experiment_to_dict(experiment)), 201

# Add notification routes
@app.route('/api/notifications', methods=['GET'])
@jwt_required()
def get_notifications():
    username = get_jwt_identity()
    unread_only = request.args.get('unread_only', 'false').lower() == 'true'
    
    notifications = notification_service.get_user_notifications(username, unread_only)
    return jsonify([n.to_dict() for n in notifications])

@app.route('/api/notifications/<notification_id>/read', methods=['POST'])
@jwt_required()
def mark_notification_read(notification_id):
    notification_service.mark_as_read(notification_id)
    return jsonify({"message": "Notification marked as read"})

@app.route('/api/notifications/<notification_id>/dismiss', methods=['POST'])
@jwt_required()
def dismiss_notification(notification_id):
    notification_service.mark_as_dismissed(notification_id)
    return jsonify({"message": "Notification dismissed"})

@app.route('/api/notifications/<notification_id>', methods=['DELETE'])
@jwt_required()
def delete_notification(notification_id):
    success = notification_service.delete_notification(notification_id)
    if success:
        return jsonify({"message": "Notification deleted"})
    else:
        return jsonify({"error": "Notification not found"}), 404

# WebSocket event handlers for notifications
@socketio.on('connect')
def handle_connect():
    print('Client connected')
    
    # Add user to their own room for targeted notifications
    user = get_jwt_identity() if request.args.get('token') else None
    if user:
        join_room(f'user_{user}')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

# Update existing handlers to trigger notifications

# Modify handle_step_start to send notifications
def handle_step_start(step_id, start_time=None):
    # Existing step start logic...
    
    # Send notification for next ready step
    for step in scheduler.schedule.values():
        if step.status == StepStatus.READY:
            # Find the experiment for this step
            for exp in scheduler.experiments.values():
                if step.id in exp.steps:
                    notification = notification_factories["step_ready"](step, exp)
                    notification_service.create_notification(notification)
                    break

# Modify handle_step_complete to send notifications
def handle_step_complete(step_id, end_time=None):
    # Get the step before completing it
    step = scheduler.get_step(step_id)
    
    # Find the experiment
    experiment = None
    for exp in scheduler.experiments.values():
        if step_id in exp.steps:
            experiment = exp
            break
    
    # Complete the step
    # Existing step complete logic...
    
    # Send completion notification
    if experiment:
        notification = notification_factories["step_completed"](step, experiment)
        notification_service.create_notification(notification)
    
    # Check for resource conflicts in newly ready steps
    check_resource_conflicts()

# Add resource conflict detection
def check_resource_conflicts():
    running_resources = {}  # resource -> step
    
    # Find all running steps and their resources
    for step in scheduler.schedule.values():
        if step.status == StepStatus.RUNNING and step.resource_needed:
            if step.resource_needed in running_resources:
                # Conflict detected!
                conflicting_step = running_resources[step.resource_needed]
                
                # Find the experiment
                for exp in scheduler.experiments.values():
                    if step.id in exp.steps or conflicting_step.id in exp.steps:
                        experiment = exp
                        notification = notification_factories["resource_conflict"](
                            step, conflicting_step, experiment, step.resource_needed
                        )
                        notification_service.create_notification(notification)
                        break
            else:
                running_resources[step.resource_needed] = step

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
    
    # Start the Flask app on port 5001 to avoid macOS AirTunes conflict on port 5000
    socketio.run(app, debug=True, port=5001, host='0.0.0.0')
