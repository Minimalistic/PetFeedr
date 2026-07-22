#!/usr/bin/env python3

import schedule
import subprocess
import time
from datetime import date

from feeder_core import load_and_schedule_feedings, log, setup_logging
from DRV8825 import SIMULATION_MODE


def run():
    """Main run loop - loads schedules and runs them."""
    log.info("Starting to load feeding times from file.")

    try:
        load_and_schedule_feedings()
        log.info("Finished loading feeding times from file.")
    except Exception as e:
        log.error(f"Error reading feeding_schedules.txt: {str(e)}")

    log.info("Starting schedule execution.")
    last_date = date.today()

    while True:
        # Check if it's a new day - regenerate randomized schedule
        if date.today() != last_date:
            log.info("New day detected - regenerating schedule with fresh randomization")
            try:
                load_and_schedule_feedings()
                last_date = date.today()
            except Exception as e:
                log.error(f"Error regenerating schedule: {e}")

        schedule.run_pending()
        time.sleep(1)


def run_web_interface():
    """Start the web interface using subprocess."""
    subprocess.Popen(["python3", "web_interface.py"])


def main():
    setup_logging()
    if SIMULATION_MODE:
        log.info("=" * 50)
        log.info("🔧 PETFEEDR RUNNING IN SIMULATION MODE")
        log.info("   No hardware will be touched!")
        log.info("=" * 50)

    run_web_interface()
    log.info("PetFeedr started successfully!")
    run()


if __name__ == "__main__":
    main()
