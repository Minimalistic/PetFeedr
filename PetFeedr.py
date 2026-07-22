#!/usr/bin/env python3

import logging
import schedule
import subprocess
import time
from datetime import date

from feeder_core import load_and_schedule_feedings
from DRV8825 import SIMULATION_MODE


def run():
    """Main run loop - loads schedules and runs them."""
    logging.info("Starting to load feeding times from file.")

    try:
        load_and_schedule_feedings()
        logging.info("Finished loading feeding times from file.")
    except Exception as e:
        logging.error(f"Error reading feeding_schedules.txt: {str(e)}")

    logging.info("Starting schedule execution.")
    last_date = date.today()

    while True:
        # Check if it's a new day - regenerate randomized schedule
        if date.today() != last_date:
            logging.info("New day detected - regenerating schedule with fresh randomization")
            try:
                load_and_schedule_feedings()
                last_date = date.today()
            except Exception as e:
                logging.error(f"Error regenerating schedule: {e}")

        schedule.run_pending()
        time.sleep(1)


def run_web_interface():
    """Start the web interface using subprocess."""
    subprocess.Popen(["python3", "web_interface.py"])


def main():
    if SIMULATION_MODE:
        logging.info("=" * 50)
        logging.info("🔧 PETFEEDR RUNNING IN SIMULATION MODE")
        logging.info("   No hardware will be touched!")
        logging.info("=" * 50)

    run_web_interface()
    logging.info("PetFeedr started successfully!")
    run()


if __name__ == "__main__":
    main()
