import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional, Dict, Any
import bcrypt

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    DateTime,
    ForeignKey,
    Table,
    Text,
    Boolean,
    JSON,
)
from sqlalchemy.orm import relationship

from db import db


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
        # ``first_start_time`` is set ONLY on the very first start() call and
        # is never overwritten on resume-after-pause. It exists for reporting:
        # ``actual_start_time`` is repurposed on resume to point at the latest
        # resume instant (so we can compute "time since last resume" without
        # storing both fields). If you need "when did this step originally
        # begin", read ``first_start_time``.
        self.first_start_time: Optional[datetime] = None
        self.actual_end_time: Optional[datetime] = None
        self.elapsed_time: timedelta = timedelta(0) # Time accumulated while running
        self.status: StepStatus = StepStatus.PENDING

        # Dynamic adjustments
        self.latest_allowed_start_time: Optional[datetime] = None # Calculated by scheduler
        self.earliest_possible_start_time: Optional[datetime] = None # Calculated by scheduler

    def start(self, start_time: Optional[datetime] = None):
        """Marks the step as started.

        Two cases:

        * From READY: the very first start of this step. We set both
          ``actual_start_time`` and ``first_start_time`` to ``now``, leave
          ``elapsed_time`` at zero.
        * From PAUSED: a resume. We update ``actual_start_time`` to ``now``
          (so "now - actual_start_time" measures time since the latest
          resume) and DO NOT touch ``elapsed_time``. ``elapsed_time`` already
          holds the accumulated work from prior runs; ``pause()`` adds the
          most-recent run's slice to it, and ``complete()`` adds the final
          slice. Resetting elapsed_time here would silently drop prior work.
          ``first_start_time`` is preserved across resumes.
        """
        if self.status not in [StepStatus.READY, StepStatus.PAUSED]:
             # Consider raising an error or logging a warning
             print(f"Warning: Cannot start step '{self.name}' with status {self.status.value}")
             return

        self.actual_start_time = start_time or datetime.now()
        # Set first_start_time only on the FIRST start. Resumes (status was
        # PAUSED) leave it untouched so it can answer "when did this step
        # originally begin?" for reports.
        if self.first_start_time is None:
            self.first_start_time = self.actual_start_time
        self.status = StepStatus.RUNNING
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
        """Compute the expected wall-clock end time, accounting for elapsed.

        Cases:

        * RUNNING: the most recent resume happened at ``actual_start_time``,
          and ``elapsed_time`` holds work accumulated from earlier runs (zero
          if this is the first run). Time still owed = ``duration - elapsed``.
          Expected end = ``actual_start_time + (duration - elapsed_time)``.
          Note: this is correct even on the first run because elapsed=0 then,
          which collapses to ``actual_start_time + duration``.
        * PAUSED: not currently accruing time. If we resumed right now we'd
          finish ``duration - elapsed_time`` later, so expected end =
          ``now + (duration - elapsed_time)``.
        * COMPLETED: return ``actual_end_time`` verbatim.
        * Anything else (PENDING/READY/SKIPPED/ERROR): fall back to
          ``scheduled_start_time + duration`` if we have one, else ``None``.

        Remaining time is floored at zero so a step that's already over its
        budget doesn't return an end time before its start.
        """
        if self.status == StepStatus.COMPLETED and self.actual_end_time:
            return self.actual_end_time

        if self.status == StepStatus.RUNNING and self.actual_start_time:
            remaining = self.duration - self.elapsed_time
            if remaining < timedelta(0):
                remaining = timedelta(0)
            return self.actual_start_time + remaining

        if self.status == StepStatus.PAUSED:
            remaining = self.duration - self.elapsed_time
            if remaining < timedelta(0):
                remaining = timedelta(0)
            return datetime.now() + remaining

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


# ---------------------------------------------------------------------------
# ORM models -- own write-side state. The dataclasses above remain the shape
# the API serializes; `to_dataclass` / `from_dataclass` bridge the layers.
# ---------------------------------------------------------------------------

# Self-referential many-to-many: a step depends on N other steps.
step_dependencies = Table(
    "step_dependencies",
    db.metadata,
    Column("dependent_id", String, ForeignKey("steps.id", ondelete="CASCADE"), primary_key=True),
    Column("dependency_id", String, ForeignKey("steps.id", ondelete="CASCADE"), primary_key=True),
)


class UserORM(db.Model):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    username = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    # Map of experiment_id -> permission ("view"/"edit"). JSON column for simplicity;
    # in U3 this may be normalized into a real share table. For U2 the dataclass
    # already stores it as a dict, so JSON is the lowest-friction port.
    shared_experiments = Column(JSON, nullable=False, default=dict)

    @classmethod
    def from_dataclass(cls, user: "User") -> "UserORM":
        return cls(
            id=user.id,
            username=user.username,
            email=user.email,
            password_hash=user.password_hash,
            shared_experiments=dict(user.shared_experiments),
        )

    def to_dataclass(self) -> "User":
        # Build a User without re-hashing -- bypass __init__ to keep the
        # existing password_hash bytes intact.
        u = User.__new__(User)
        u.id = self.id
        u.username = self.username
        u.email = self.email
        u.password_hash = self.password_hash
        u.shared_experiments = dict(self.shared_experiments or {})
        return u

    def apply_dataclass(self, user: "User") -> None:
        """Copy mutable fields from a dataclass back into this ORM row."""
        self.username = user.username
        self.email = user.email
        self.password_hash = user.password_hash
        self.shared_experiments = dict(user.shared_experiments)


class ExperimentORM(db.Model):
    __tablename__ = "experiments"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    owner = Column(String, ForeignKey("users.username"), nullable=True, index=True)
    # username -> permission. JSON dict mirrors the dataclass shape.
    shared_with = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    steps = relationship(
        "StepORM",
        back_populates="experiment",
        cascade="all, delete-orphan",
        order_by="StepORM.created_at",
    )

    @classmethod
    def from_dataclass(cls, experiment: "Experiment") -> "ExperimentORM":
        orm = cls(
            id=experiment.id,
            name=experiment.name,
            description=experiment.description,
            owner=getattr(experiment, "owner", None),
            shared_with=dict(getattr(experiment, "shared_with", {}) or {}),
        )
        for step in experiment.steps.values():
            orm.steps.append(StepORM.from_dataclass(step, experiment_id=experiment.id))
        return orm

    def to_dataclass(self) -> "Experiment":
        exp = Experiment.__new__(Experiment)
        exp.id = self.id
        exp.name = self.name
        exp.description = self.description
        exp.steps = {}
        # owner / shared_with are extras the route handlers attach -- preserve them.
        exp.owner = self.owner
        exp.shared_with = dict(self.shared_with or {})
        for step_orm in self.steps:
            exp.steps[step_orm.id] = step_orm.to_dataclass()
        return exp


class StepORM(db.Model):
    __tablename__ = "steps"

    id = Column(String, primary_key=True)
    experiment_id = Column(String, ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    duration_seconds = Column(Float, nullable=False, default=0.0)
    step_type = Column(String, nullable=False, default=StepType.FIXED_DURATION.value)
    status = Column(String, nullable=False, default=StepStatus.PENDING.value)
    notes = Column(Text, nullable=True)
    resource_needed = Column(String, nullable=True)
    step_metadata = Column(JSON, nullable=False, default=dict)

    scheduled_start_time = Column(DateTime, nullable=True)
    scheduled_end_time = Column(DateTime, nullable=True)
    actual_start_time = Column(DateTime, nullable=True)
    # ``first_start_time`` records the very first start() and is never
    # overwritten by resume-after-pause; ``actual_start_time`` always points
    # at the latest start/resume. Both are needed for accurate reporting.
    first_start_time = Column(DateTime, nullable=True)
    actual_end_time = Column(DateTime, nullable=True)
    elapsed_seconds = Column(Float, nullable=False, default=0.0)
    earliest_possible_start_time = Column(DateTime, nullable=True)
    latest_allowed_start_time = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    experiment = relationship("ExperimentORM", back_populates="steps")

    # Self-referential many-to-many over the association table. ``dependencies``
    # lists steps THIS step depends on (i.e. "parents" in DAG terms).
    dependencies = relationship(
        "StepORM",
        secondary=step_dependencies,
        primaryjoin=id == step_dependencies.c.dependent_id,
        secondaryjoin=id == step_dependencies.c.dependency_id,
        backref="dependents",
    )

    @classmethod
    def from_dataclass(cls, step: "Step", experiment_id: str) -> "StepORM":
        return cls(
            id=step.id,
            experiment_id=experiment_id,
            name=step.name,
            duration_seconds=step.duration.total_seconds() if step.duration else 0.0,
            step_type=step.step_type.value,
            status=step.status.value,
            notes=step.notes,
            resource_needed=step.resource_needed,
            step_metadata=dict(step.metadata or {}),
            scheduled_start_time=step.scheduled_start_time,
            scheduled_end_time=step.scheduled_end_time,
            actual_start_time=step.actual_start_time,
            first_start_time=getattr(step, "first_start_time", None),
            actual_end_time=step.actual_end_time,
            elapsed_seconds=step.elapsed_time.total_seconds() if step.elapsed_time else 0.0,
            earliest_possible_start_time=step.earliest_possible_start_time,
            latest_allowed_start_time=step.latest_allowed_start_time,
        )

    def apply_dataclass(self, step: "Step") -> None:
        """Copy mutable state from a dataclass step back onto this ORM row.

        Used by upsert paths to preserve in-flight RUNNING state across PUTs.
        Dependency relationships are NOT touched here -- callers manage those
        via the association table.
        """
        self.name = step.name
        self.duration_seconds = step.duration.total_seconds() if step.duration else 0.0
        self.step_type = step.step_type.value
        self.status = step.status.value
        self.notes = step.notes
        self.resource_needed = step.resource_needed
        self.step_metadata = dict(step.metadata or {})
        self.scheduled_start_time = step.scheduled_start_time
        self.scheduled_end_time = step.scheduled_end_time
        self.actual_start_time = step.actual_start_time
        self.first_start_time = getattr(step, "first_start_time", None)
        self.actual_end_time = step.actual_end_time
        self.elapsed_seconds = step.elapsed_time.total_seconds() if step.elapsed_time else 0.0
        self.earliest_possible_start_time = step.earliest_possible_start_time
        self.latest_allowed_start_time = step.latest_allowed_start_time

    def to_dataclass(self) -> "Step":
        step = Step.__new__(Step)
        step.id = self.id
        step.name = self.name
        step.duration = timedelta(seconds=self.duration_seconds or 0.0)
        step.step_type = StepType(self.step_type)
        step.status = StepStatus(self.status)
        step.notes = self.notes
        step.resource_needed = self.resource_needed
        step.metadata = dict(self.step_metadata or {})
        step.scheduled_start_time = self.scheduled_start_time
        step.scheduled_end_time = self.scheduled_end_time
        step.actual_start_time = self.actual_start_time
        step.first_start_time = self.first_start_time
        step.actual_end_time = self.actual_end_time
        step.elapsed_time = timedelta(seconds=self.elapsed_seconds or 0.0)
        step.earliest_possible_start_time = self.earliest_possible_start_time
        step.latest_allowed_start_time = self.latest_allowed_start_time
        # Dependency IDs are stored on the dataclass as a list of step IDs.
        step.dependencies = [d.id for d in (self.dependencies or [])]
        return step


class TemplateORM(db.Model):
    __tablename__ = "templates"

    id = Column(String, primary_key=True)
    owner = Column(String, ForeignKey("users.username"), nullable=False, index=True)
    name = Column(String, nullable=False)
    source_experiment_id = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    # Steps payload stays as denormalized JSON -- templates are write-once
    # snapshots, not relational data we query into.
    steps_payload = Column(JSON, nullable=False, default=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "source_experiment_id": self.source_experiment_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "steps": list(self.steps_payload or []),
        }


class NotificationORM(db.Model):
    __tablename__ = "notifications"

    id = Column(String, primary_key=True)
    target_user = Column(String, ForeignKey("users.username"), nullable=False, index=True)
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    type = Column(String, nullable=False)
    priority = Column(String, nullable=False)
    experiment_id = Column(String, nullable=True)
    step_id = Column(String, nullable=True)
    notification_metadata = Column(JSON, nullable=False, default=dict)
    actions = Column(JSON, nullable=False, default=list)
    delivery_methods = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    is_read = Column(Boolean, nullable=False, default=False)
    is_dismissed = Column(Boolean, nullable=False, default=False)
