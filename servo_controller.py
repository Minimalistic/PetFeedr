import time
import logging
from DRV8825 import DRV8825, SIMULATION_MODE


def trigger_servo():
    """Trigger the motor to dispense food."""
    start_time = time.time()
    Motor1 = None

    try:
        Motor1 = DRV8825(dir_pin=13, step_pin=19, enable_pin=12, mode_pins=(16, 17, 20))
        Motor1.SetMicroStep('softward', 'fullstep')

        # Rotate forward to dispense food
        Motor1.TurnStep(Dir='forward', steps=100, stepdelay=0.005)
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
