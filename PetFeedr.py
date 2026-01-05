#!/usr/bin/env python3

import os
import schedule
import logging
from logging.handlers import TimedRotatingFileHandler
import subprocess
import requests
from servo_controller import trigger_servo
from DRV8825 import SIMULATION_MODE

# Import secrets - handle missing keys gracefully for optional features
try:
    from SecretKeys import PETFEEDR_USER_ID, PETFEEDR_PASSWORD
except ImportError:
    PETFEEDR_USER_ID = "admin"
    PETFEEDR_PASSWORD = "admin"
    logging.warning("SecretKeys.py not found - using default credentials")

try:
    from SecretKeys import PETFEEDR_SECRET_KEY
except ImportError:
    PETFEEDR_SECRET_KEY = "dev-secret-key-change-me"

# Pushover is optional - check if configured
try:
    from SecretKeys import PUSHOVER_API_TOKEN, PUSHOVER_USER_KEY, PUSHOVER_ENABLED
except ImportError:
    PUSHOVER_API_TOKEN = None
    PUSHOVER_USER_KEY = None
    PUSHOVER_ENABLED = False

# Allow environment variable to override Pushover setting
if os.environ.get('PUSHOVER_ENABLED', '').lower() == 'false':
    PUSHOVER_ENABLED = False

# Configure logging
log_file = 'feeding_log.txt'
handler = TimedRotatingFileHandler(log_file, when='D', backupCount=14)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logging.getLogger('').addHandler(handler)
logging.getLogger('').setLevel(logging.INFO)

# Also log to console for easier development
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logging.getLogger('').addHandler(console_handler)


def send_pushover_msg(title, message):
    """Send push notification using Pushover API (if enabled)."""
    # Skip if Pushover is not configured or disabled
    if not PUSHOVER_ENABLED or not PUSHOVER_API_TOKEN or not PUSHOVER_USER_KEY:
        logging.debug(f"Pushover disabled - would send: {title}")
        return
    
    # Skip in simulation mode to avoid spamming during development
    if SIMULATION_MODE:
        logging.info(f"[SIM] 📱 Would send Pushover: {title} - {message}")
        return
    
    url = "https://api.pushover.net/1/messages.json"
    data = {
        "token": PUSHOVER_API_TOKEN,
        "user": PUSHOVER_USER_KEY,
        "title": title,
        "message": message
    }
    
    try:
        response = requests.post(url, data=data)
        if response.status_code == 200:
            logging.info("Pushover notification sent successfully.")
        else:
            logging.warning(f"Pushover failed: {response.status_code}")
    except Exception as e:
        logging.error(f"Pushover error: {e}")


def get_hopper_ascii(level):
    if level == 100:
        return """
            _____________
            |◍◍◍◍◍◍◍◍◍◍◍|
            |◍◍◍◍◍◍◍◍◍◍◍|
            |◍◍◍◍◍◍◍◍◍◍◍|
            |\◍◍◍◍◍◍◍◍◍/|
            | \◍◍◍◍◍◍◍/ |
            |  \◍◍◍◍◍/  |
            |   \◍◍◍/   |
            |    \◍/    |
            |   [ @ ]   |
            |    | |    |
            ||___| |___||
            |\         /|
            | \       / |
            |  \     /  |
            |   \   /   |
            |    \ /    |
            |    | |    |
            |____| |____| 
            \___________/  
        """
    elif level == 75:
        return """
            _____________
            |           |
            |           |
            |◍ ◍ ◍ ◍ ◍ ◍|
            |\◍◍◍◍◍◍◍◍◍/|
            | \◍◍◍◍◍◍◍/ |
            |  \◍◍◍◍◍/  |
            |   \◍◍◍/   |
            |    \◍/    |
            |   [ @ ]   |
            |    | |    |
            ||___| |___||
            |\         /|
            | \       / |
            |  \     /  |
            |   \   /   |
            |    \ /    |
            |    | |    |
            |____| |____| 
            \___________/  
        """
    # Add more conditions for other levels
    return ""


def feed_pet(is_scheduled=False):
    try:
        # Dispense food to the pet using the servo
        trigger_servo()
        logging.info("Triggering Servo to feed the pet")
        logging.info(" > ^ <")
        logging.info("( o.o ) Food dispensed successfully!")
        logging.info(" /\\_/\\💕")
        send_pushover_msg(title="Petfeedr fed your pet!",
                          message="Petfeedr fed your pet!")
    except Exception as e:
        logging.error(f"Error feeding pet: {str(e)}")


def run():
    # Load feeding times from file
    logging.info("Starting to load feeding times from file.")
    # TODO has no validation for duplicates
    try:
        if not os.path.isfile('feeding_schedules.txt'):
            open('feeding_schedules.txt', 'w').close()
            logging.info("feeding_schedules.txt not found. An empty file has been created.")
        
        with open('feeding_schedules.txt', 'r') as file:
            lines = file.readlines()
            if len(lines) == 0:
                logging.warning("feeding_schedules.txt is empty. Starting with an empty schedule.")
            else:
                for line in lines:
                    hour, minute = line.strip().split(':')
                    schedule.every().day.at(f"{hour}:{minute}").do(feed_pet)
                    logging.info(f"Event found in schedules file! - Added: {hour}:{minute}")
        logging.info("Finished loading feeding times from file.")
    except Exception as e:
        logging.error(f"Error reading feeding_schedules.txt: {str(e)}")

    logging.info("Starting schedule execution.")
    while True:
        schedule.run_pending()
        logging.debug("Checking for pending scheduled tasks.")


def run_web_interface():
    # Start the web interface using subprocess
    subprocess.Popen(["python3", "web_interface.py"])


def validate_login(user_id, password):
    # Validate user login credentials
    return user_id == PETFEEDR_USER_ID and password == PETFEEDR_PASSWORD


def main():
    # Log startup mode
    if SIMULATION_MODE:
        logging.info("=" * 50)
        logging.info("🔧 PETFEEDR RUNNING IN SIMULATION MODE")
        logging.info("   No hardware will be touched!")
        logging.info("=" * 50)
    
    run_web_interface()  # Start web server
    send_pushover_msg(title="Petfeedr has started!",
                      message="Petfeedr started successfully!")
    run()  # Run PetFeedr


if __name__ == "__main__":
    main()
