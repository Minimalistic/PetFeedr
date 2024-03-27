import schedule
import time
import logging

# Configure logging
logging.basicConfig(filename='feeding_log.txt', level=logging.INFO,
                    format='%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

def feed_pet():
    # TODO: Replace this with actual servo control
    logging.info("Feeding the pet")

def setup_schedule():
    # Currently no pre-populated schedules, keeping around as I believe it's used by the web interface
    pass

def run():
    # Load feeding times from file
    try:
        with open('feeding_schedules.txt', 'r') as file:
            for line in file:
                hour, minute = line.strip().split(':')
                schedule.every().day.at(f"{hour}:{minute}").do(feed_pet)
                logging.info(f"Loaded feeding time: {hour}:{minute}")  # Log the loaded feeding time
    except FileNotFoundError:
        logging.warning("feeding_schedules.txt not found. Starting with an empty schedule.")
    except Exception as e:
        logging.error(f"Error reading feeding_schedules.txt: {str(e)}")

    while True:
        schedule.run_pending()

import subprocess

def run_web_interface():
    subprocess.Popen(["python3", "web_interface.py"])

if __name__ == "__main__":
    run_web_interface() # Start web server
    run() # Run PetFeedr
