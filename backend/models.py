import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional, Dict, Any
import bcrypt

class StepStatus(Enum):
    PENDING = "pending"
    READY = "ready" # Dependencies met, can be started
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    ERROR = "error" # If something went wrong during execution

class StepType(Enum):
    FIXED_DURATION = "fixed_duration" # Timer countdown; cannot pause/stop; signals completion.
    TASK = "task"           # User-driven; tracks elapsed time; can pause/stop; requires user attention.
    FIXED_START = "fixed_start"     # Timer count-up; cannot pause/stop; duration sets earliest start for dependents.
    AUTOMATED_TASK = "automated_task" # Runs for set time; cannot pause; blocks a resource but frees user.
    # Removed WAIT
    # Add more types as needed

class Step:
    def __init__(
        self,
        name: str,
        duration: timedelta,
        step_type: StepType = StepType.FIXED_DURATION,
        dependencies: Optional[List[str]] = None, # List of Step IDs this step depends on
        scheduled_start_time: Optional[datetime] = None,
        notes: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None, # For extra info specific to a step type
        resource_needed: Optional[str] = None # e.g., 'microscope', 'user_attention', 'oven'
    ):
        self.id: str = str(uuid.uuid4()) # Unique identifier for the step
        self.name: str = name
        self.duration: timedelta = duration # Expected duration
        self.step_type: StepType = step_type
        self.dependencies: List[str] = dependencies if dependencies else []
        self.notes: Optional[str] = notes
        self.metadata: Dict[str, Any] = metadata if metadata else {}
        self.resource_needed: Optional[str] = resource_needed

        # Default resource needed based on type (can be overridden)
        if self.resource_needed is None:
            if self.step_type == StepType.TASK:
                 self.resource_needed = 'user_attention'
            # Add other defaults if needed (e.g., AUTOMATED_TASK for 'microscope')

        # Scheduling and Execution State
        self.scheduled_start_time: Optional[datetime] = scheduled_start_time
        self.scheduled_end_time: Optional[datetime] = (
            scheduled_start_time + duration if scheduled_start_time else None
        )
        self.actual_start_time: Optional[datetime] = None
        self.actual_end_time: Optional[datetime] = None
        self.elapsed_time: timedelta = timedelta(0) # Time accumulated while running
        self.status: StepStatus = StepStatus.PENDING

        # Dynamic adjustments
        self.latest_allowed_start_time: Optional[datetime] = None # Calculated by scheduler
        self.earliest_possible_start_time: Optional[datetime] = None # Calculated by scheduler

    def start(self, start_time: Optional[datetime] = None):
        """Marks the step as started."""
        if self.status not in [StepStatus.READY, StepStatus.PAUSED]:
             # Consider raising an error or logging a warning
             print(f"Warning: Cannot start step '{self.name}' with status {self.status.value}")
             return

        self.actual_start_time = start_time or datetime.now()
        self.status = StepStatus.RUNNING
        # Reset elapsed time if restarting after pause? Or accumulate? Let's accumulate for now.
        print(f"Step '{self.name}' started at {self.actual_start_time}")

    def pause(self):
        """Pauses the step, if supported by its type."""
        # FIXED_DURATION, FIXED_START, and AUTOMATED_TASK steps cannot be paused.
        if self.step_type in [StepType.FIXED_DURATION, StepType.FIXED_START, StepType.AUTOMATED_TASK]:
            print(f"Warning: Cannot pause step '{self.name}' of type {self.step_type.value}")
            return

        if self.status == StepStatus.RUNNING:
            now = datetime.now()
            self.elapsed_time += now - self.actual_start_time # Add time since last start/resume
            self.status = StepStatus.PAUSED
            print(f"Step '{self.name}' paused at {now}. Total elapsed: {self.elapsed_time}")
        else:
             print(f"Warning: Cannot pause step '{self.name}' with status {self.status.value}")


    def complete(self, end_time: Optional[datetime] = None):
        """Marks the step as completed."""
        if self.status not in [StepStatus.RUNNING, StepStatus.PAUSED]: # Allow completing paused steps? Maybe.
            print(f"Warning: Cannot complete step '{self.name}' with status {self.status.value}")
            return

        self.actual_end_time = end_time or datetime.now()
        if self.status == StepStatus.RUNNING:
            # Add any remaining time since last start/resume
             self.elapsed_time += self.actual_end_time - self.actual_start_time

        self.status = StepStatus.COMPLETED
        print(f"Step '{self.name}' completed at {self.actual_end_time}. Final elapsed: {self.elapsed_time}")


    def update_status(self, status: StepStatus):
        """Allows manually setting status (e.g., to SKIPPED or ERROR)."""
        self.status = status
        print(f"Step '{self.name}' status updated to {status.value}")

    def get_expected_end_time(self) -> Optional[datetime]:
        """Calculates the expected end time based on start time and duration."""
        if self.actual_start_time:
             # If running or paused, calculate based on elapsed time
             if self.status in [StepStatus.RUNNING, StepStatus.PAUSED]:
                 remaining_time = self.duration - self.elapsed_time
                 if remaining_time < timedelta(0): remaining_time = timedelta(0) # Ensure not negative
                 # For running step, expected end is now + remaining
                 # For paused step, we don't know when it will resume, so this is less certain
                 # Let's just return start + duration for simplicity for now, scheduler will refine
                 return self.actual_start_time + self.duration # Simplified view
             elif self.status == StepStatus.COMPLETED and self.actual_end_time:
                 return self.actual_end_time

        if self.scheduled_start_time:
             return self.scheduled_start_time + self.duration

        return None # Not enough info to determine

    def __repr__(self):
        return (f"Step(id={self.id}, name='{self.name}', status={self.status.value}, "
                f"scheduled_start={self.scheduled_start_time}, actual_start={self.actual_start_time}, "
                f"duration={self.duration})")

# We will also need an Experiment class to hold these steps
class Experiment:
    def __init__(self, name: str, description: Optional[str] = None):
        self.id: str = str(uuid.uuid4())
        self.name: str = name
        self.description: Optional[str] = description
        self.steps: Dict[str, Step] = {} # Store steps by their ID for easy lookup
        # Maybe add overall experiment status, start/end times etc. later

    def add_step(self, step: Step):
        if step.id in self.steps:
            print(f"Warning: Step with ID {step.id} already exists in experiment '{self.name}'.")
            return
        self.steps[step.id] = step
        print(f"Step '{step.name}' added to experiment '{self.name}'.")

    def get_step(self, step_id: str) -> Optional[Step]:
        return self.steps.get(step_id)

    def __repr__(self):
        return f"Experiment(id={self.id}, name='{self.name}', num_steps={len(self.steps)})"

# Later, we'll add a Scheduler class to manage multiple Experiments and their Steps 

class User:
    def __init__(self, username: str, email: str, password: str):
        self.id: str = str(uuid.uuid4())
        self.username: str = username
        self.email: str = email
        self.password_hash: str = self._hash_password(password)
        self.shared_experiments: Dict[str, str] = {}  # experiment_id -> permission
    
    def _hash_password(self, password: str) -> str:
        # Generate a salted hash of the password
        password_bytes = password.encode('utf-8')
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode('utf-8')
    
    def check_password(self, password: str) -> bool:
        # Check if the provided password matches the stored hash
        password_bytes = password.encode('utf-8')
        hashed_bytes = self.password_hash.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hashed_bytes) 