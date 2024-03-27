#!/usr/bin/env python3

from flask import Flask, render_template, request, redirect
import schedule
import time
import logging
from threading import Thread

app = Flask(__name__)

# Configure logging
logging.basicConfig(filename='feeding_log.txt', level=logging.INFO,
                    format='%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

def run_schedule():
    while True:
        schedule.run_pending()
        time.sleep(1)

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
    return render_template('index.html', scheduled_jobs=scheduled_jobs, log_messages=''.join(log_messages))

@app.route('/add', methods=['POST'])
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
def feed_now():
    feed_pet()
    logging.info("Manually fed the pet")
    return redirect('/')

def feed_pet():
    # TODO: Replace this with actual servo control
    logging.info("Feeding the pet")

if __name__ == '__main__':
    schedule_thread = Thread(target=run_schedule)
    schedule_thread.start()
    app.run(host='0.0.0.0', port=5000, debug=True)
