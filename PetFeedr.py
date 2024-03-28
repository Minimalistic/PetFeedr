import time
import schedule
import logging
import subprocess
from servo_controller import trigger_servo
from SecretKey import VALID_USER_ID, VALID_PASSWORD
from multiprocessing import Process

# Configure logging
logging.basicConfig(filename='feeding_log.txt', level=logging.INFO,
                    format='%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

def feed_pet():
    try:
        # Dispense food to the pet using the servo
        logging.info("Triggering Servo to feed the pet! 🐱")
        trigger_servo()
        logging.info("Food dispensed successfully!")
    except Exception as e:
        logging.error(f"Error feeding pet: {str(e)}")

def setup_schedule():
    # Currently no pre-populated schedules, keeping around as I believe it's used by the web interface
    pass

def run():
    # Load feeding times from file
    # TODO has no validation for duplicates
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

def run_web_interface():
    subprocess.Popen(["python3", "web_interface.py"])

def validate_login(user_id, password):
    return user_id == VALID_USER_ID and password == VALID_PASSWORD

def main():
    run_web_interface() # Start web server
    run() # Run PetFeedr

if __name__ == "__main__":
    main()
