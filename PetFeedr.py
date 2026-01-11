#!/usr/bin/env python3

import os
import random
import json
import schedule
import logging
from logging.handlers import TimedRotatingFileHandler
import subprocess
from datetime import datetime, timedelta, date
import time
from servo_controller import trigger_servo, PORTION_SIZES, DEFAULT_PORTION
from DRV8825 import SIMULATION_MODE

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

# File to store today's randomized schedule (for web UI display)
TODAYS_SCHEDULE_FILE = 'todays_schedule.json'


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
    return ""


def feed_pet(portion=DEFAULT_PORTION):
    """Feed the pet with the specified portion size."""
    try:
        trigger_servo(portion=portion)
        logging.info("Triggering Servo to feed the pet")
        logging.info(" > ^ <")
        logging.info("( o.o ) Food dispensed successfully!")
        logging.info(" /\\_/\\💕")
    except Exception as e:
        logging.error(f"Error feeding pet: {str(e)}")


def parse_schedule_line(line):
    """Parse a schedule line into components.
    
    Format: "HH:MM,portion[,fixed]"
    Returns: (time_str, portion, is_fixed)
    """
    parts = line.strip().split(',')
    time_str = parts[0].strip()
    
    portion = DEFAULT_PORTION
    is_fixed = False
    
    if len(parts) > 1:
        portion = parts[1].strip()
        if portion not in PORTION_SIZES:
            portion = DEFAULT_PORTION
    
    if len(parts) > 2 and parts[2].strip().lower() == 'fixed':
        is_fixed = True
    
    return time_str, portion, is_fixed


def apply_random_offset(time_str, range_minutes, all_times):
    """Apply a random offset to a time, avoiding conflicts with other times.
    
    Args:
        time_str: Original time in "HH:MM" format
        range_minutes: Max offset in either direction
        all_times: List of already-scheduled times to avoid (as datetime objects)
    
    Returns:
        New time string in "HH:MM" format
    """
    base_time = datetime.strptime(time_str, "%H:%M")
    
    # Try up to 10 times to find a non-conflicting time
    for _ in range(10):
        offset = random.randint(-range_minutes, range_minutes)
        new_time = base_time + timedelta(minutes=offset)
        
        # Keep within same day (0:00 - 23:59)
        if new_time.hour < 0 or (new_time.day != base_time.day and offset < 0):
            new_time = base_time  # Don't go before midnight
        
        # Check for conflicts (within 10 minutes of another feeding)
        conflict = False
        for other_time in all_times:
            diff = abs((new_time - other_time).total_seconds() / 60)
            if diff < 10 and diff > 0:  # Within 10 minutes
                conflict = True
                break
        
        if not conflict:
            return new_time.strftime("%H:%M")
    
    # If we couldn't find a good time, just use original
    return time_str


def load_and_schedule_feedings():
    """Load feeding times and schedule them with randomization for non-fixed times."""
    # Default randomization range: ±30 minutes
    range_minutes = 30
    
    schedule.clear()  # Clear existing schedules
    
    if not os.path.isfile('feeding_schedules.txt'):
        open('feeding_schedules.txt', 'w').close()
        logging.info("feeding_schedules.txt not found. An empty file has been created.")
        return []
    
    todays_schedule = []
    scheduled_times = []  # Track times to avoid conflicts
    
    with open('feeding_schedules.txt', 'r') as file:
        lines = file.readlines()
    
    if len(lines) == 0:
        logging.warning("feeding_schedules.txt is empty. Starting with an empty schedule.")
        return []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        time_str, portion, is_fixed = parse_schedule_line(line)
        
        # Apply randomization if not fixed
        if not is_fixed:
            actual_time = apply_random_offset(time_str, range_minutes, scheduled_times)
            logging.info(f"Randomized: {time_str} → {actual_time} ({portion} portion)")
        else:
            actual_time = time_str
            logging.info(f"Fixed time: {actual_time} ({portion} portion)")
        
        # Track this time for conflict avoidance
        scheduled_times.append(datetime.strptime(actual_time, "%H:%M"))
        
        # Schedule the feeding
        schedule.every().day.at(actual_time).do(lambda p=portion: feed_pet(portion=p))
        
        # Store for today's schedule display
        todays_schedule.append({
            'base_time': time_str,
            'actual_time': actual_time,
            'portion': portion,
            'is_fixed': is_fixed,
            'randomized': actual_time != time_str
        })
    
    # Save today's schedule for web UI
    save_todays_schedule(todays_schedule)
    
    return todays_schedule


def save_todays_schedule(schedule_data):
    """Save today's randomized schedule for web UI display."""
    data = {
        'date': date.today().isoformat(),
        'schedule': schedule_data
    }
    try:
        with open(TODAYS_SCHEDULE_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.error(f"Error saving today's schedule: {e}")


def load_todays_schedule():
    """Load today's schedule. Returns None if needs regeneration."""
    if not os.path.exists(TODAYS_SCHEDULE_FILE):
        return None
    
    try:
        with open(TODAYS_SCHEDULE_FILE, 'r') as f:
            data = json.load(f)
        
        # Check if it's from today
        if data.get('date') == date.today().isoformat():
            return data.get('schedule', [])
        else:
            return None  # Needs regeneration for new day
    except Exception as e:
        logging.error(f"Error loading today's schedule: {e}")
        return None


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
