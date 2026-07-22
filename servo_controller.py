import time
import logging
from DRV8825 import DRV8825, SIMULATION_MODE

# Shared app logger by name — importing it from feeder_core would be circular
log = logging.getLogger('petfeedr')

# Base unit calibration (2026-01-11)
# One dispense cycle = 100 steps ≈ 1/4 cup
BASE_STEPS = 100
AGITATION_STEPS = 40

# Portion sizes defined as number of dispense cycles
# Each cycle dispenses ~1/4 cup for consistency
PORTION_SIZES = {
    'small':  (1, '~1/4 cup'),   # 1 cycle
    'medium': (2, '~1/2 cup'),   # 2 cycles  
    'large':  (3, '~3/4 cup'),   # 3 cycles
}

# Default portion if none specified
DEFAULT_PORTION = 'small'


def get_portion_cycles(portion_name):
    """Get the number of dispense cycles for a given portion size."""
    if portion_name in PORTION_SIZES:
        return PORTION_SIZES[portion_name][0]
    return PORTION_SIZES[DEFAULT_PORTION][0]


def get_portion_description(portion_name):
    """Get the human-readable description for a portion size."""
    if portion_name in PORTION_SIZES:
        return PORTION_SIZES[portion_name][1]
    return PORTION_SIZES[DEFAULT_PORTION][1]


def trigger_servo(portion='small'):
    """Trigger the motor to dispense food.
    
    Args:
        portion: Size of portion to dispense ('small', 'medium', 'large')
    
    Larger portions are dispensed as multiple cycles of the base unit
    for more consistent results.
    """
    start_time = time.time()
    Motor1 = None
    
    # Get number of cycles for the requested portion
    num_cycles = get_portion_cycles(portion)
    portion_desc = get_portion_description(portion)

    try:
        Motor1 = DRV8825(dir_pin=13, step_pin=19, enable_pin=12, mode_pins=(16, 17, 20))
        
        # Use 1/16 microstepping for quieter operation and better torque management
        Motor1.SetMicroStep('softward', '1/16step')

        log.info(f"Dispensing {portion} portion ({portion_desc}) - {num_cycles} cycle(s)")

        for cycle in range(num_cycles):
            if num_cycles > 1:
                log.info(f"  Cycle {cycle + 1}/{num_cycles}")
            
            # 1. Agitation: Rotate backward slightly to dislodge any jams
            Motor1.TurnStep(Dir='backward', steps=AGITATION_STEPS, stepdelay=0.0005)
            time.sleep(0.1)

            # 2. Dispense: Rotate forward (base steps + recover agitation)
            total_steps = BASE_STEPS + AGITATION_STEPS
            Motor1.TurnStep(Dir='forward', steps=total_steps, stepdelay=0.0005)
            
            # Brief pause between cycles
            if cycle < num_cycles - 1:
                time.sleep(0.3)

        elapsed = time.time() - start_time
        if SIMULATION_MODE:
            log.info(f"[SIM] ✅ Feeding completed in {elapsed:.2f}s ({portion} portion)")
        else:
            log.info(f"Feeding completed in {elapsed:.2f}s ({portion} portion)")

    except Exception as e:
        log.exception("An error occurred while triggering the servo:")
        if Motor1:
            Motor1.Stop()
            log.info("Motor stopped due to an exception")

    finally:
        if Motor1:
            Motor1.Stop()
            log.debug("Motor stopped and cleaned up")
