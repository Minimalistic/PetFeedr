#!/usr/bin/env python3

import os
import schedule
import logging
from logging.handlers import TimedRotatingFileHandler
import subprocess
import requests
from servo_controller import trigger_servo

from SecretKeys import PETFEEDR_USER_ID,            \
                        PETFEEDR_PASSWORD,      \
                        PUSHOVER_API_TOKEN,      \
                        PUSHOVER_USER_KEY         

# Configure logging
log_file = 'feeding_log.txt'
handler = TimedRotatingFileHandler(log_file, when='D', backupCount=14)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logging.getLogger('').addHandler(handler)
logging.getLogger('').setLevel(logging.INFO) # Logging options (DEBUG=Verbose): 
                                             # DEBUG, INFO, WARNING, ERROR, CRITICAL

def send_pushover_msg(title, message):
    # Send push notification using Pushover API
    url = "https://api.pushover.net/1/messages.json"
    data = {
        "token"     : PUSHOVER_API_TOKEN,
        "user"      : PUSHOVER_USER_KEY,
        "title"     : title,
        "message"   : message
    }
    
    response = requests.post(url, data=data)
    
    if response.status_code == 200:
        logging.info("Pushover notification sent successfully.")
    else:
        logging.info("Pushover failed to send notification.")

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

def feed_pet(is_scheduled=False):
    try:
        # Dispense food to the pet using the servo
        trigger_servo()
        logging.info("Triggering Servo to feed the pet")
        logging.info(" > ^ <")
        logging.info("( o.o ) Food dispensed successfully!")
        logging.info(" /\_/\💕")
        send_pushover_msg(title="Petfeedr fed your pet!", \
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
                    logging.info(f"Event found in schedules file! - Added: {hour}:{minute}")  # Log the loaded feeding time
        logging.info("Finished loading feeding times from file.")
    except Exception as e:
        logging.error(f"Error reading feeding_schedules.txt: {str(e)}")

    logging.info("Starting schedule execution.")
    while True:
        schedule.run_pending()

def run_web_interface():
    # Start the web interface using subprocess
    subprocess.Popen(["python3", "web_interface.py"])

def validate_login(user_id, password):
    # Validate user login credentials
    return user_id == PETFEEDR_USER_ID and password == PETFEEDR_PASSWORD

def main():
    run_web_interface() # Start web server
    send_pushover_msg(title="Petfeedr has started!", \
                                message="Petfeedr started successfully!")
    run() # Run PetFeedr

if __name__ == "__main__":
    main()
