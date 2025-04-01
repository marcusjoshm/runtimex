from datetime import datetime, timedelta
import time # For simulating delays (optional)

from models import Experiment, Step, StepStatus, StepType
from scheduler import Scheduler

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

# --- Main Test Scenario --- 
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

    # 3. Instantiate Scheduler and Add Experiment
    scheduler = Scheduler()
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
    run_test()
