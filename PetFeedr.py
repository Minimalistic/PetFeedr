#!/usr/bin/env python3

import os
import signal
import sys
import schedule
import time
from datetime import date
from threading import Thread

from feeder_core import load_and_schedule_feedings, log, setup_logging
from DRV8825 import SIMULATION_MODE
import web_interface


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


def run_web():
    """Web UI in a daemon thread of this process.

    If Flask dies (port in use, bad config), exit the whole process so
    systemd restarts it — otherwise the scheduler would keep running
    behind a silently dead UI.
    """
    try:
        web_interface.app.run(host='0.0.0.0', port=web_interface.WEB_PORT,
                              debug=False, use_reloader=False)
    except Exception:
        log.exception("Web interface crashed")
        os._exit(1)


def main():
    setup_logging()
    # SystemExit unwinds the main thread, so a SIGTERM mid-dispense (deploy,
    # service restart) still runs trigger_servo's finally: Motor.Stop()
    signal.signal(signal.SIGTERM, lambda *args: sys.exit(0))

    if SIMULATION_MODE:
        log.info("=" * 50)
        log.info("🔧 PETFEEDR RUNNING IN SIMULATION MODE")
        log.info("   No hardware will be touched!")
        log.info("=" * 50)

    Thread(target=run_web, daemon=True).start()
    log.info("PetFeedr started successfully!")
    run()


if __name__ == "__main__":
    main()
