#!/usr/bin/env python3

from flask import Flask,        \
                    redirect,   \
                    url_for,    \
                    request,    \
                    render_template
from flask_login import LoginManager,       \
                            UserMixin,      \
                            current_user,   \
                            login_required, \
                            login_user,     \
                            logout_user
import schedule
import time
import logging
from threading import Thread
from PetFeedr import validate_login, feed_pet
from SecretKey import SECRET_KEY

app = Flask(__name__)
app.secret_key = SECRET_KEY

login_manager = LoginManager()
login_manager.init_app(app)

class User(UserMixin):
    def __init__(self, id):
        self.id = id

@login_manager.user_loader
def load_user(user_id):
    return User(user_id) # Return the user object for the given user_id

# Configure logging
logging.basicConfig(filename='feeding_log.txt', level=logging.INFO,
    format='%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

def run_schedule():
    while True:
        schedule.run_pending()
        time.sleep(1)

@app.errorhandler(401)
def unauthorized(e):
    # note that we set the 401 status explicitly
    return render_template('401.html'), 401

@app.route('/')
def index():
    # Read the scheduled jobs from feeding_schedules.txt
    scheduled_jobs = []
    try:
        with open('feeding_schedules.txt', 'r') as file:
            for line in file:
                scheduled_jobs.append(line.strip())
    except FileNotFoundError:
        pass

    with open('feeding_log.txt', 'r') as file:
        log_messages = file.readlines()
    log_messages.reverse()
    return render_template('index.html', current_user=current_user, scheduled_jobs=scheduled_jobs, log_messages=''.join(log_messages))

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

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))  # Redirect to the main page after logout

@app.route('/add', methods=['POST'])
@login_required
def add_job():
    hour = request.form['hour'].zfill(2)
    minute = request.form['minute'].zfill(2)
    try:
        schedule.every().day.at(f"{hour}:{minute}").do(feed_pet)
        scheduled_time = f"{hour}:{minute}"
        with open('feeding_schedules.txt', 'a') as file:
            file.write(f"{scheduled_time}\n")
            file.flush()
        logging.info(f"Added feeding time: {scheduled_time}")
        return redirect('/')
    except schedule.ScheduleValueError:
        return "Invalid time format. Please use HH:MM format.", 400
    except Exception as e:
        logging.error(f"Error writing to feeding_schedules.txt: {str(e)}")
        return "An error occurred while adding the feeding time.", 500

@app.route('/delete', methods=['POST'])
@login_required
def delete_job():
    job_time = request.form['job_time']
    try:
        # Remove the job from the schedule
        for job in schedule.jobs:
            if job.at_time.strftime('%H:%M') == job_time:
                schedule.cancel_job(job)
                break

        # Remove the job from feeding_schedules.txt
        with open('feeding_schedules.txt', 'r') as file:
            lines = file.readlines()
        with open('feeding_schedules.txt', 'w') as file:
            for line in lines:
                if line.strip() != job_time:
                    file.write(line)

        logging.info(f"Deleted feeding time: {job_time}")
        return redirect('/')
    except Exception as e:
        logging.error(f"Error deleting feeding time: {str(e)}")
        return "An error occurred while deleting the feeding time.", 500

@app.route('/feed', methods=['POST'])
@login_required
def trigger_feeding():
    feed_pet()
    return redirect('/')

def main():
    schedule_thread = Thread(target=run_schedule)
    schedule_thread.start()
    app.run(host='0.0.0.0', port=5000, debug=True)

if __name__ == '__main__':
    main()