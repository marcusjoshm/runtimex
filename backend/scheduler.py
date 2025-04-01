from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

from models import Experiment, Step, StepStatus, StepType

class ScheduleConflictError(Exception):
    """Custom exception for scheduling conflicts."""
    pass

class Scheduler:
    def __init__(self):
        self.experiments: Dict[str, Experiment] = {}
        self.schedule: Dict[str, Step] = {} # All steps from all experiments, keyed by step ID
        # Maybe maintain a timeline view for easier conflict checking?
        # self.timeline = [] # List of (start_time, end_time, step_id)

    def add_experiment(self, experiment: Experiment):
        """Adds an experiment and its steps to the scheduler."""
        if experiment.id in self.experiments:
            print(f"Warning: Experiment '{experiment.name}' (ID: {experiment.id}) already added.")
            return
        self.experiments[experiment.id] = experiment
        for step_id, step in experiment.steps.items():
            if step_id in self.schedule:
                # This shouldn't happen if step IDs are unique UUIDs
                print(f"Warning: Step ID {step_id} conflict while adding experiment '{experiment.name}'.")
            else:
                self.schedule[step_id] = step
        print(f"Experiment '{experiment.name}' added to scheduler.")
        # self.calculate_initial_schedule() # Should we calculate immediately?

    def get_step(self, step_id: str) -> Optional[Step]:
        """Retrieve a step by its ID from the schedule."""
        return self.schedule.get(step_id)

    def _resolve_dependencies(self, step: Step) -> Optional[datetime]:
        """Find the earliest time a step can start based on its dependencies."""
        earliest_start = None
        for dep_id in step.dependencies:
            dep_step = self.get_step(dep_id)
            if not dep_step:
                print(f"Error: Dependency step ID {dep_id} not found for step '{step.name}'.")
                # Handle this error - maybe mark step as ERROR?
                return None # Cannot determine start time

            # Get the dependency's completion time (actual if available, otherwise scheduled)
            dep_end_time = dep_step.actual_end_time or dep_step.scheduled_end_time

            if not dep_end_time:
                 # This dependency hasn't finished and doesn't even have a scheduled end yet.
                 # This implies the schedule needs recalculating or the dependency needs scheduling first.
                 print(f"Warning: Dependency '{dep_step.name}' for step '{step.name}' has no end time.")
                 # For now, let's assume this means the dependent step cannot start yet.
                 return None # Cannot schedule this step yet

            if earliest_start is None or dep_end_time > earliest_start:
                earliest_start = dep_end_time

        return earliest_start

    def calculate_initial_schedule(self, start_time: Optional[datetime] = None):
        """Calculates the initial scheduled start/end times for all PENDING steps."""
        # Very basic initial scheduling: assumes sequential execution based on dependencies
        # and a provided global start time or now if none given.
        # Does NOT handle resource conflicts yet.

        base_time = start_time or datetime.now()
        processed_steps = set()
        steps_to_process = list(self.schedule.values())

        # Very naive scheduling loop - might need refinement for complex dependencies
        # A better approach might use topological sort
        MAX_ITERATIONS = len(steps_to_process) * 2 # Safety break
        iterations = 0
        while steps_to_process and iterations < MAX_ITERATIONS:
            iterations += 1
            step = steps_to_process.pop(0) # Get the next step

            if step.id in processed_steps or step.status != StepStatus.PENDING:
                continue # Skip already processed or non-pending steps

            # Check dependencies
            earliest_dep_start = self._resolve_dependencies(step)

            can_schedule = False
            if not step.dependencies:
                # No dependencies, can start at base_time (or later if specified)
                step.scheduled_start_time = step.scheduled_start_time or base_time
                can_schedule = True
            elif earliest_dep_start:
                # Dependencies resolved, schedule after the last one finishes
                step.scheduled_start_time = step.scheduled_start_time or earliest_dep_start
                can_schedule = True
            else:
                # Dependencies not met or unresolved, put back in queue
                steps_to_process.append(step)
                continue

            if can_schedule:
                 if step.scheduled_start_time:
                    step.scheduled_end_time = step.scheduled_start_time + step.duration
                    step.earliest_possible_start_time = earliest_dep_start or base_time # Store this info
                    print(f"Scheduled '{step.name}': {step.scheduled_start_time} -> {step.scheduled_end_time}")
                    processed_steps.add(step.id)
                 else:
                     # Should not happen if can_schedule is True, but safety check
                     print(f"Error: Could not determine scheduled start for '{step.name}'.")
                     steps_to_process.append(step) # Put back

        if iterations >= MAX_ITERATIONS and steps_to_process:
            print("Warning: Max scheduling iterations reached. Possible circular dependency or issue?")
            for step in steps_to_process:
                print(f" - Unschedulable: {step.name} (Status: {step.status.value}, Deps: {step.dependencies})")

        self.update_ready_status()


    def update_ready_status(self):
         """Updates steps status to READY if dependencies are met and they are PENDING."""
         now = datetime.now()
         for step in self.schedule.values():
             if step.status == StepStatus.PENDING:
                 deps_met = True
                 earliest_start_from_deps = None
                 for dep_id in step.dependencies:
                     dep_step = self.get_step(dep_id)
                     if not dep_step or dep_step.status != StepStatus.COMPLETED:
                         deps_met = False
                         break
                     # Track latest dependency completion time
                     if dep_step.actual_end_time:
                         if earliest_start_from_deps is None or dep_step.actual_end_time > earliest_start_from_deps:
                             earliest_start_from_deps = dep_step.actual_end_time

                 if deps_met:
                     # Dependencies are complete. Is it time to start based on schedule?
                     # Let's make it READY as soon as deps are met.
                     # The actual trigger might depend on scheduled time or user action.
                     step.status = StepStatus.READY
                     step.earliest_possible_start_time = earliest_start_from_deps or step.earliest_possible_start_time # Update based on actual completion
                     print(f"Step '{step.name}' is now READY.")

    # --- Placeholder methods for future implementation --- 

    def check_for_conflicts(self) -> List[Tuple[Step, Step]]:
        """Identifies steps that overlap in time and might require user intervention."""
        # This needs a more sophisticated implementation, likely checking:
        # - Multiple steps needing active user tasks simultaneously
        # - Steps scheduled too close together
        print("Conflict checking not fully implemented yet.")
        conflicts = []
        # Example naive check: iterate through all pairs of running/scheduled steps
        # sorted_steps = sorted(self.schedule.values(), key=lambda s: s.scheduled_start_time or datetime.max)
        # for i in range(len(sorted_steps)):
        #     for j in range(i + 1, len(sorted_steps)):
        #         s1 = sorted_steps[i]
        #         s2 = sorted_steps[j]
        #         # Check for overlap logic here...
        return conflicts

    def handle_step_start(self, step_id: str, start_time: Optional[datetime] = None):
        """Handles the logic when a step starts, potentially adjusting the schedule."""
        step = self.get_step(step_id)
        if step:
            actual_start = start_time or datetime.now()
            step.start(actual_start)
            # Check if the start time affects subsequent steps
            # self.reschedule_dependents(step)
            # self.check_for_conflicts()
            print(f"Handling start for step '{step.name}'. Rescheduling needed? TBD.")
            self.update_ready_status() # Update statuses which might depend on this start
        else:
            print(f"Error: Cannot handle start for unknown step ID {step_id}")

    def handle_step_pause(self, step_id: str):
        """Handles the logic when a step is paused."""
        step = self.get_step(step_id)
        if step:
             step.pause()
             # Pausing might delay dependent steps
             # self.reschedule_dependents(step)
             print(f"Handling pause for step '{step.name}'. Rescheduling needed? TBD.")
        else:
             print(f"Error: Cannot handle pause for unknown step ID {step_id}")

    def handle_step_complete(self, step_id: str, end_time: Optional[datetime] = None):
        """Handles the logic when a step completes, potentially triggering dependents."""
        step = self.get_step(step_id)
        if step:
            actual_end = end_time or datetime.now()
            step.complete(actual_end)
            # Update dependents' earliest start time and check if they become ready
            self.update_ready_status()
            # Potentially reschedule dependents if completion time differs from scheduled
            # self.reschedule_dependents(step)
            # self.check_for_conflicts()
            print(f"Handling completion for step '{step.name}'. Ready status updated.")
        else:
            print(f"Error: Cannot handle completion for unknown step ID {step_id}")

    def get_upcoming_steps(self, window: timedelta = timedelta(hours=1)) -> List[Step]:
        """Returns steps that are scheduled or expected to start soon."""
        now = datetime.now()
        upcoming = []
        for step in self.schedule.values():
            if step.status in [StepStatus.READY, StepStatus.PENDING]:
                start_time_to_check = step.scheduled_start_time or step.earliest_possible_start_time
                if start_time_to_check and now <= start_time_to_check < now + window:
                    upcoming.append(step)
            elif step.status == StepStatus.RUNNING:
                expected_end = step.get_expected_end_time()
                if expected_end and now <= expected_end < now + window:
                    # Include running steps nearing completion
                    upcoming.append(step)

        return sorted(upcoming, key=lambda s: s.scheduled_start_time or s.earliest_possible_start_time or datetime.max)

    # More methods will be needed for dynamic rescheduling, conflict resolution etc. 