#!/usr/bin/env python3

import time
import logging
from threading import Thread
from PetFeedr import get_hopper_ascii, validate_login, feed_pet
from SecretKeys import PETFEEDR_SECRET_KEY
from datetime import datetime
from flask import Flask, redirect, url_for, request, render_template
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
import schedule

app = Flask(__name__)
app.secret_key = PETFEEDR_SECRET_KEY

login_manager = LoginManager()
login_manager.init_app(app)

# Custom Jinja2 filter for formatting datetime objects
@app.template_filter('strftime')
def _jinja2_filter_datetime(value, format=None):
    return value

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, id):
        self.id = id

# Function to read and format feeding times from a file
def read_and_format_times(filename):
    with open(filename, 'r') as file:
        times = file.readlines()

    # Remove newline characters
    times = [time.strip() for time in times]

    # Convert to datetime objects
    times = [datetime.strptime(time, "%H:%M") for time in times]

    # Sort the feeding times by time
    times.sort()

    # Convert to 12-hour format
    times = [time.strftime("%I:%M %p") for time in times]

    # Find the index of the first PM time
    pm_index = next((i for i, time in enumerate(times) if 'PM' in time), len(times))

    # Insert a separator at the PM index so it's easier to parse in the UI (Actual -separator- "pointer" is in index > jinja)
    times.insert(pm_index, '-separator-')

    return times

# User loader function for Flask-Login
@login_manager.user_loader
def load_user(user_id):
    return User(user_id)

# Configure logging
logging.basicConfig(filename='feeding_log.txt', level=logging.INFO,
    format='%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# Function to run the schedule in a separate thread
def run_schedule():
    while True:
        schedule.run_pending()
        time.sleep(1)

# Error handler for unauthorized access
@app.errorhandler(401)
def unauthorized(e):
    # Note that we set the 401 status explicitly
    return render_template('401.html'), 401

# Route for the home page
@app.route('/')
def index():
    # Read and format the scheduled jobs from feeding_schedules.txt
    scheduled_jobs = read_and_format_times('feeding_schedules.txt')
    hopper_level = 100  # Placeholder for the hopper level until more refined.
    hopper_ascii = get_hopper_ascii(hopper_level)
    with open('feeding_log.txt', 'r') as file:
        log_messages = file.readlines()
    log_messages.reverse()
    return render_template('index.html', hopper_ascii=hopper_ascii, current_user=current_user, scheduled_jobs=scheduled_jobs, log_messages=''.join(log_messages))

# Route for the login page
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_id = request.form['user_id']
        password = request.form['password']
        # Validate the user_id and password here
        if validate_login(user_id, password):
            user = User(user_id)
            login_user(user)
            return redirect(url_for('index'))  # Redirect to the main page after login
    return render_template('login.html')  # Render the login form

# Route for logging out
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))  # Redirect to the main page after logout

# Route for adding a feeding job
@app.route('/add', methods=['POST'])
@login_required
def add_job():
    feeding_time = request.form['feeding_time']

    try:
        # Check if the feeding time already exists in feeding_schedules.txt
        with open('feeding_schedules.txt', 'r') as file:
            existing_times = file.readlines()
        existing_times = [time.strip() for time in existing_times]
        if feeding_time in existing_times:
            return "Feeding time already exists. <a href='/'>Go back</a>", 400

        # Add the feeding time to the schedule
        schedule.every().day.at(feeding_time).do(feed_pet)

        # Write the feeding time to feeding_schedules.txt
        with open('feeding_schedules.txt', 'a') as file:
            file.write(f"{feeding_time}\n")
            file.flush()

        # Log the added feeding time in 12-hour format
        feeding_time_12h = datetime.strptime(feeding_time, "%H:%M").strftime("%I:%M %p")
        logging.info(f"Added feeding time: {feeding_time_12h}")

        return redirect('/')

    except schedule.ScheduleValueError:
        return "Invalid time format. Please use HH:MM format.", 400

    except Exception as e:
        logging.error(f"Error writing to feeding_schedules.txt: {str(e)}")
        return "An error occurred while adding the feeding time.", 500
    
# Route for deleting a feeding job
@app.route('/delete', methods=['POST'])
@login_required
def delete_job():
    job_time = request.form['job_time']
    try:
        # Convert the job time back to 24-hour format
        job_time_24h = datetime.strptime(job_time, "%I:%M %p").strftime("%H:%M")

        # Remove the job from the schedule
        for job in schedule.jobs:
            if job.at_time.strftime('%H:%M') == job_time_24h:
                schedule.cancel_job(job)
                break

        # Remove the job from feeding_schedules.txt
        with open('feeding_schedules.txt', 'r') as file:
            lines = file.readlines()
        with open('feeding_schedules.txt', 'w') as file:
            for line in lines:
                if line.strip() != job_time_24h:
                    file.write(line)

        logging.info(f"Deleted feeding time: {job_time}")
        return redirect('/')
    except Exception as e:
        logging.error(f"Error deleting feeding time: {str(e)}")
        return "An error occurred while deleting the feeding time.", 500
    
# Route for triggering a feeding manually
@app.route('/feed', methods=['POST'])
@login_required
def trigger_feeding():
    feed_pet()
    return redirect('/')

# Main function to start the application
def main():
    schedule_thread = Thread(target=run_schedule)
    schedule_thread.start()
    app.run(host='0.0.0.0', port=5000, debug=True)

if __name__ == '__main__':
    main()
