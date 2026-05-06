from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

from db import db
from models import (
    Experiment,
    Step,
    StepStatus,
    StepType,
    ExperimentORM,
    StepORM,
)


class ScheduleConflictError(Exception):
    """Custom exception for scheduling conflicts."""
    pass


class Scheduler:
    """In-memory scheduler backed by SQLAlchemy persistence.

    The dataclass cache (``self._experiments``, ``self._schedule``) is the
    source the API serializes from. Every mutation also fans out to the ORM
    via ``db.session`` so a restart can rehydrate.

    On first access (or after ``hydrate_from_db()``) the cache is populated
    from ``ExperimentORM``. Tests can call ``hydrate_from_db`` inside a fresh
    app context to simulate a restart.
    """

    def __init__(self):
        self._experiments: Dict[str, Experiment] = {}
        self._schedule: Dict[str, Step] = {}
        self._hydrated = False

    # ------------------------------------------------------------------
    # Cache-as-a-property accessors. Routes use scheduler.experiments today;
    # keeping the attribute API means main.py changes stay minimal.
    # ------------------------------------------------------------------
    @property
    def experiments(self) -> Dict[str, Experiment]:
        if not self._hydrated:
            try:
                self.hydrate_from_db()
            except RuntimeError:
                # Outside of an app context (e.g. some unit tests instantiate
                # Scheduler bare). Fall back to the empty cache.
                pass
        return self._experiments

    @property
    def schedule(self) -> Dict[str, Step]:
        if not self._hydrated:
            try:
                self.hydrate_from_db()
            except RuntimeError:
                pass
        return self._schedule

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    def hydrate_from_db(self) -> None:
        """Reload the in-memory cache from ExperimentORM."""
        self._experiments = {}
        self._schedule = {}
        for exp_orm in ExperimentORM.query.all():
            exp_dc = exp_orm.to_dataclass()
            self._experiments[exp_dc.id] = exp_dc
            for step_id, step_dc in exp_dc.steps.items():
                self._schedule[step_id] = step_dc
        self._hydrated = True

    def reset_cache(self) -> None:
        """Drop the cache; next access rehydrates. Test helper."""
        self._experiments = {}
        self._schedule = {}
        self._hydrated = False

    def _persist_experiment(self, experiment: Experiment) -> None:
        """Insert (or replace) an experiment + its steps."""
        existing = db.session.get(ExperimentORM, experiment.id)
        if existing is not None:
            db.session.delete(existing)
            db.session.flush()
        orm = ExperimentORM.from_dataclass(experiment)
        db.session.add(orm)
        db.session.flush()
        # Wire dependency many-to-many AFTER all steps are flushed so FKs resolve.
        self._sync_step_dependencies(experiment, orm)
        db.session.commit()

    def _sync_step_dependencies(self, experiment: Experiment, orm: ExperimentORM) -> None:
        """Sync StepORM.dependencies association rows from the dataclass shape."""
        steps_by_id = {s.id: s for s in orm.steps}
        for dc_step in experiment.steps.values():
            target = steps_by_id.get(dc_step.id)
            if target is None:
                continue
            target.dependencies = [
                steps_by_id[d_id] for d_id in dc_step.dependencies if d_id in steps_by_id
            ]

    def _persist_step_state(self, step: Step) -> None:
        """Update only the mutable runtime state of a step (status, times)."""
        orm = db.session.get(StepORM, step.id)
        if orm is None:
            return
        orm.apply_dataclass(step)
        db.session.commit()

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------
    def add_experiment(self, experiment: Experiment):
        """Adds an experiment + its steps. Persists to DB and updates cache."""
        if experiment.id in self.experiments:
            print(f"Warning: Experiment '{experiment.name}' (ID: {experiment.id}) already added.")
            return
        self._persist_experiment(experiment)
        self._experiments[experiment.id] = experiment
        for step_id, step in experiment.steps.items():
            self._schedule[step_id] = step
        print(f"Experiment '{experiment.name}' added to scheduler.")

    def upsert_experiment_steps(
        self,
        experiment: Experiment,
        incoming_steps: List[Step],
    ) -> None:
        """Reconcile ``experiment.steps`` against ``incoming_steps`` by ID.

        Existing steps with a matching ID keep their runtime state (status,
        actual_start_time, elapsed_time) -- only editable fields (name,
        duration, type, notes, resource, dependencies) are updated.

        Steps in the incoming list that aren't currently on the experiment
        are added. Steps on the experiment that aren't in the incoming list
        are removed.

        This is the fix for the audit's wipe-and-recreate bug in PUT.
        """
        incoming_by_id = {s.id: s for s in incoming_steps if s.id}
        existing_ids = set(experiment.steps.keys())

        # Remove orphans first.
        for old_id in list(existing_ids - set(incoming_by_id.keys())):
            old_step = experiment.steps.pop(old_id, None)
            if old_step is not None:
                self._schedule.pop(old_id, None)

        # Apply edits + adds. Incoming step instances may carry a `.id`
        # generated client-side; we treat that as the dedup key.
        for inc in incoming_steps:
            if inc.id in experiment.steps:
                target = experiment.steps[inc.id]
                # Preserve runtime state -- only copy editable fields.
                target.name = inc.name
                target.duration = inc.duration
                target.step_type = inc.step_type
                target.dependencies = list(inc.dependencies)
                target.notes = inc.notes
                target.resource_needed = inc.resource_needed
                # Re-derive scheduled_end_time if a scheduled_start exists.
                if target.scheduled_start_time:
                    target.scheduled_end_time = target.scheduled_start_time + target.duration
            else:
                experiment.steps[inc.id] = inc
                self._schedule[inc.id] = inc

        # Persist the whole experiment back to DB. We rebuild the row but
        # the dataclass now carries preserved runtime state for surviving
        # steps, so the new ORM rows reflect that state.
        self._persist_experiment(experiment)

    def remove_experiment(self, experiment_id: str) -> bool:
        """Delete an experiment and cascade to its steps."""
        orm = db.session.get(ExperimentORM, experiment_id)
        if orm is None and experiment_id not in self._experiments:
            return False
        if orm is not None:
            db.session.delete(orm)
            db.session.commit()
        exp = self._experiments.pop(experiment_id, None)
        if exp is not None:
            for sid in list(exp.steps.keys()):
                self._schedule.pop(sid, None)
        return True

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
                return None

            dep_end_time = dep_step.actual_end_time or dep_step.scheduled_end_time

            if not dep_end_time:
                 print(f"Warning: Dependency '{dep_step.name}' for step '{step.name}' has no end time.")
                 return None

            if earliest_start is None or dep_end_time > earliest_start:
                earliest_start = dep_end_time

        return earliest_start

    def calculate_initial_schedule(self, start_time: Optional[datetime] = None):
        """Calculates the initial scheduled start/end times for all PENDING steps."""
        base_time = start_time or datetime.now()
        processed_steps = set()
        steps_to_process = list(self.schedule.values())

        MAX_ITERATIONS = len(steps_to_process) * 2
        iterations = 0
        while steps_to_process and iterations < MAX_ITERATIONS:
            iterations += 1
            step = steps_to_process.pop(0)

            if step.id in processed_steps or step.status != StepStatus.PENDING:
                continue

            earliest_dep_start = self._resolve_dependencies(step)

            can_schedule = False
            if not step.dependencies:
                step.scheduled_start_time = step.scheduled_start_time or base_time
                can_schedule = True
            elif earliest_dep_start:
                step.scheduled_start_time = step.scheduled_start_time or earliest_dep_start
                can_schedule = True
            else:
                steps_to_process.append(step)
                continue

            if can_schedule:
                 if step.scheduled_start_time:
                    step.scheduled_end_time = step.scheduled_start_time + step.duration
                    step.earliest_possible_start_time = earliest_dep_start or base_time
                    print(f"Scheduled '{step.name}': {step.scheduled_start_time} -> {step.scheduled_end_time}")
                    processed_steps.add(step.id)
                 else:
                     print(f"Error: Could not determine scheduled start for '{step.name}'.")
                     steps_to_process.append(step)

        if iterations >= MAX_ITERATIONS and steps_to_process:
            print("Warning: Max scheduling iterations reached. Possible circular dependency or issue?")

        self.update_ready_status()

        # Persist mutated step state back to DB.
        try:
            for step in self._schedule.values():
                self._persist_step_state(step)
        except RuntimeError:
            # Out of app context; tests that don't need persistence skip this.
            pass

    def update_ready_status(self):
         """Updates steps status to READY if dependencies are met and they are PENDING."""
         for step in self.schedule.values():
             if step.status == StepStatus.PENDING:
                 deps_met = True
                 earliest_start_from_deps = None
                 for dep_id in step.dependencies:
                     dep_step = self.get_step(dep_id)
                     if not dep_step or dep_step.status != StepStatus.COMPLETED:
                         deps_met = False
                         break
                     if dep_step.actual_end_time:
                         if earliest_start_from_deps is None or dep_step.actual_end_time > earliest_start_from_deps:
                             earliest_start_from_deps = dep_step.actual_end_time

                 if deps_met:
                     step.status = StepStatus.READY
                     step.earliest_possible_start_time = (
                         earliest_start_from_deps or step.earliest_possible_start_time
                     )
                     print(f"Step '{step.name}' is now READY.")

    def check_for_conflicts(self) -> List[Tuple[Step, Step]]:
        """Identifies steps that overlap in time and might require user intervention."""
        # Real implementation lands in U6.
        return []

    def handle_step_start(self, step_id: str, start_time: Optional[datetime] = None):
        """Handles the logic when a step starts."""
        step = self.get_step(step_id)
        if step:
            actual_start = start_time or datetime.now()
            step.start(actual_start)
            self._persist_step_state(step)
            self.update_ready_status()
            try:
                for s in self._schedule.values():
                    self._persist_step_state(s)
            except RuntimeError:
                pass
            print(f"Handling start for step '{step.name}'.")
        else:
            print(f"Error: Cannot handle start for unknown step ID {step_id}")

    def handle_step_pause(self, step_id: str):
        """Handles the logic when a step is paused."""
        step = self.get_step(step_id)
        if step:
            step.pause()
            self._persist_step_state(step)
            print(f"Handling pause for step '{step.name}'.")
        else:
            print(f"Error: Cannot handle pause for unknown step ID {step_id}")

    def handle_step_complete(self, step_id: str, end_time: Optional[datetime] = None):
        """Handles the logic when a step completes."""
        step = self.get_step(step_id)
        if step:
            actual_end = end_time or datetime.now()
            step.complete(actual_end)
            self._persist_step_state(step)
            self.update_ready_status()
            try:
                for s in self._schedule.values():
                    self._persist_step_state(s)
            except RuntimeError:
                pass
            print(f"Handling completion for step '{step.name}'.")
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
                    upcoming.append(step)

        return sorted(
            upcoming,
            key=lambda s: s.scheduled_start_time or s.earliest_possible_start_time or datetime.max,
        )
