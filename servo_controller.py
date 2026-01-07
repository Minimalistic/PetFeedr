import time
import logging
from DRV8825 import DRV8825, SIMULATION_MODE


def trigger_servo():
    """Trigger the motor to dispense food."""
    start_time = time.time()
    Motor1 = None

    try:
        Motor1 = DRV8825(dir_pin=13, step_pin=19, enable_pin=12, mode_pins=(16, 17, 20))
        
        # Use 1/16 microstepping for quieter operation and better torque management
        # 'softward' means we control the microstep pins via software
        Motor1.SetMicroStep('softward', '1/16step')

        # Agitation Sequence:
        # 1. Rotate backward slightly to dislodge any potential jams
        logging.info("Starting agitation sequence (backward)")
        Motor1.TurnStep(Dir='backward', steps=160, stepdelay=0.0005) # ~10% of a rotation
        time.sleep(0.1)

        # 2. Rotate forward to dispense food
        #    Full dispense (1600) + recovering the backward agitataion (160) = 1760 steps
        logging.info("Dispensing food (forward)")
        Motor1.TurnStep(Dir='forward', steps=1760, stepdelay=0.0005)
        time.sleep(0.1)

        elapsed = time.time() - start_time
        if SIMULATION_MODE:
            logging.info(f"[SIM] ✅ Feeding cycle completed in {elapsed:.2f}s")
        else:
            logging.info(f"Feeding cycle completed in {elapsed:.2f}s")

    except Exception as e:
        logging.exception("An error occurred while triggering the servo:")
        # Stop the motor if an exception occurs
        if Motor1:
            Motor1.Stop()
            logging.info("Motor stopped due to an exception")

    finally:
        # Ensure the motor is stopped and cleaned up properly
        if Motor1:
            Motor1.Stop()
            logging.debug("Motor stopped and cleaned up")
