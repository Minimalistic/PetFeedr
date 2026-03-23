#!/usr/bin/env python3

import os
import re
import time
import json
import logging
from threading import Thread
from PetFeedr import feed_pet, load_todays_schedule, save_todays_schedule, apply_random_offset, TODAYS_SCHEDULE_FILE
from servo_controller import PORTION_SIZES, DEFAULT_PORTION
from DRV8825 import SIMULATION_MODE

APP_VERSION = "1.1.0"

# Configurable port - default 5000, override with PETFEEDR_PORT env var
WEB_PORT = int(os.environ.get('PETFEEDR_PORT', 5000))
from datetime import datetime, timedelta
from flask import Flask, redirect, url_for, request, render_template, jsonify
import schedule

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(24).hex())


def wants_json():
    """Check if the client prefers a JSON response."""
    return request.accept_mimetypes.best_match(
        ['application/json', 'text/html']) == 'application/json'

# Custom Jinja2 filter for formatting datetime objects
@app.template_filter('strftime')
def _jinja2_filter_datetime(value, format=None):
    return value


def read_schedules_with_details():
    """Read feeding schedules with all details including fixed status and today's actual times."""
    try:
        with open('feeding_schedules.txt', 'r') as file:
            lines = file.readlines()
    except FileNotFoundError:
        return []
    
    # Load today's randomized schedule
    todays_schedule = load_todays_schedule() or []
    todays_by_base = {s['base_time']: s for s in todays_schedule}
    
    schedules = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        parts = line.split(',')
        time_str = parts[0].strip()
        
        portion = DEFAULT_PORTION
        is_fixed = False
        
        if len(parts) > 1:
            portion = parts[1].strip()
            if portion not in PORTION_SIZES and portion != 'fixed':
                portion = DEFAULT_PORTION
        
        if len(parts) > 2 and parts[2].strip().lower() == 'fixed':
            is_fixed = True
        elif len(parts) > 1 and parts[1].strip().lower() == 'fixed':
            is_fixed = True
            portion = DEFAULT_PORTION
        
        # Get today's actual time if available
        today_info = todays_by_base.get(time_str, {})
        actual_time = today_info.get('actual_time', time_str)
        
        try:
            base_dt = datetime.strptime(time_str, "%H:%M")
            actual_dt = datetime.strptime(actual_time, "%H:%M")
            schedules.append({
                'base_time_24h': time_str,
                'base_time_12h': base_dt.strftime("%I:%M %p"),
                'actual_time_24h': actual_time,
                'actual_time_12h': actual_dt.strftime("%I:%M %p"),
                'portion': portion,
                'is_fixed': is_fixed,
                'randomized': actual_time != time_str,
                'sort_key': actual_dt
            })
        except ValueError:
            logging.error(f"Error parsing time: {time_str}")
            continue
    
    # Sort by actual time
    schedules.sort(key=lambda x: x['sort_key'])
    
    return schedules


def calculate_daily_total(schedules):
    """Calculate total cups per day from scheduled feedings."""
    cups_per_portion = {
        'small': 0.25,
        'medium': 0.50,
        'large': 0.75,
    }
    
    total_cups = 0
    for sched in schedules:
        if isinstance(sched, dict):
            total_cups += cups_per_portion.get(sched.get('portion', 'small'), 0.25)
    
    return total_cups


def get_next_feeding(schedules):
    """Get the next upcoming feeding from the schedule."""
    if not schedules:
        return None
    
    now = datetime.now()
    current_time = now.strftime("%H:%M")
    
    for sched in schedules:
        if sched['actual_time_24h'] > current_time:
            return sched
    
    # If no upcoming feeding today, return the first one (for tomorrow)
    return schedules[0] if schedules else None


def mark_past_feedings(schedules):
    """Mark which feedings are past and which is next."""
    now = datetime.now()
    current_time = now.strftime("%H:%M")
    found_next = False
    
    for sched in schedules:
        if sched['actual_time_24h'] < current_time:
            sched['is_past'] = True
            sched['is_next'] = False
        elif not found_next:
            sched['is_past'] = False
            sched['is_next'] = True
            found_next = True
        else:
            sched['is_past'] = False
            sched['is_next'] = False
    
    return schedules


def parse_recent_activity(days=14, limit=50):
    """Parse feeding log to extract recent activity in a user-friendly format."""
    try:
        with open('feeding_log.txt', 'r') as file:
            lines = file.readlines()
    except FileNotFoundError:
        return []
    
    activity = []
    cutoff_date = datetime.now() - timedelta(days=days)
    
    # Patterns to match different log entries
    # Manual feeding: "Manual feeding triggered (medium portion)"
    # Scheduled feeding: "Feeding at 08:00 AM (small portion)"
    manual_pattern = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - Manual feeding triggered \((\w+) portion\)')
    scheduled_pattern = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - Feeding at .* \((\w+) portion\)')
    
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        
        # Try manual feeding pattern
        match = manual_pattern.match(line)
        if match:
            timestamp_str, portion = match.groups()
            try:
                timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                if timestamp < cutoff_date:
                    break
                
                activity.append({
                    'date': format_activity_date(timestamp),
                    'time': timestamp.strftime("%I:%M %p"),
                    'portion': portion,
                    'type': 'manual'
                })
            except ValueError:
                continue
            
            if len(activity) >= limit:
                break
            continue
        
        # Try scheduled feeding pattern
        match = scheduled_pattern.match(line)
        if match:
            timestamp_str, portion = match.groups()
            try:
                timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                if timestamp < cutoff_date:
                    break
                
                activity.append({
                    'date': format_activity_date(timestamp),
                    'time': timestamp.strftime("%I:%M %p"),
                    'portion': portion,
                    'type': 'scheduled'
                })
            except ValueError:
                continue
            
            if len(activity) >= limit:
                break
    
    return activity


def format_activity_date(dt):
    """Format a date for activity display (Today, Yesterday, or date)."""
    today = datetime.now().date()
    activity_date = dt.date()
    
    if activity_date == today:
        return "Today"
    elif activity_date == today - timedelta(days=1):
        return "Yesterday"
    elif activity_date >= today - timedelta(days=6):
        return dt.strftime("%A")  # Day name
    else:
        return dt.strftime("%b %d")  # "Jan 05"


def parse_weekly_stats():
    """Aggregate feeding data for the last 7 days by portion size."""
    try:
        with open('feeding_log.txt', 'r') as file:
            lines = file.readlines()
    except FileNotFoundError:
        return []

    today = datetime.now().date()
    stats = {}
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        stats[d.isoformat()] = {
            'date': d.isoformat(),
            'day_label': d.strftime('%a'),
            'is_today': d == today,
            'small': 0, 'medium': 0, 'large': 0,
            'total_cups': 0.0
        }

    cups_map = {'small': 0.25, 'medium': 0.50, 'large': 0.75}
    manual_pat = re.compile(r'^(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2} - Manual feeding triggered \((\w+) portion\)')
    sched_pat = re.compile(r'^(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2} - Feeding at .* \((\w+) portion\)')

    for line in lines:
        match = manual_pat.match(line.strip()) or sched_pat.match(line.strip())
        if match:
            date_str, portion = match.groups()
            if date_str in stats and portion in cups_map:
                stats[date_str][portion] += 1
                stats[date_str]['total_cups'] += cups_map[portion]

    return list(stats.values())


# Configure logging
logging.basicConfig(filename='feeding_log.txt', level=logging.INFO,
    format='%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')


def run_schedule():
    while True:
        schedule.run_pending()
        time.sleep(1)


@app.route('/')
def index():
    schedules = read_schedules_with_details()
    schedules = mark_past_feedings(schedules)
    
    daily_total = calculate_daily_total(schedules)
    next_feeding = get_next_feeding(schedules)
    recent_activity = parse_recent_activity(days=14, limit=30)
    all_fed_today = bool(schedules) and all(s.get('is_past') for s in schedules)
    last_feeding = recent_activity[0] if recent_activity else None

    # Timeline data
    for s in schedules:
        h, m = s['actual_time_24h'].split(':')
        s['time_minutes'] = int(h) * 60 + int(m)

    if schedules:
        times_min = [s['time_minutes'] for s in schedules]
        timeline_start = max(0, min(times_min) - 60)
        timeline_end = min(1439, max(times_min) + 60)
    else:
        timeline_start, timeline_end = 360, 1320  # 6AM-10PM default

    timeline_hours = []
    first_hour = ((timeline_start // 60) + 1) * 60
    for mins in range(first_hour, timeline_end, 120):
        h = mins // 60
        label = f"{h % 12 or 12}{'AM' if h < 12 else 'PM'}"
        pct = ((mins - timeline_start) / (timeline_end - timeline_start)) * 100
        timeline_hours.append({'label': label, 'pct': pct})

    # Weekly stats
    weekly_stats = parse_weekly_stats()
    max_daily_cups = max((d['total_cups'] for d in weekly_stats), default=0.5)
    max_daily_cups = max(max_daily_cups, 0.5)

    portion_info = {name: desc for name, (cycles, desc) in PORTION_SIZES.items()}

    return render_template('index.html',
                           schedules=schedules,
                           next_feeding=next_feeding,
                           recent_activity=recent_activity,
                           portion_sizes=PORTION_SIZES,
                           portion_info=portion_info,
                           default_portion=DEFAULT_PORTION,
                           daily_total=daily_total,
                           all_fed_today=all_fed_today,
                           simulation_mode=SIMULATION_MODE,
                           app_version=APP_VERSION,
                           last_feeding=last_feeding,
                           timeline_start=timeline_start,
                           timeline_end=timeline_end,
                           timeline_hours=timeline_hours,
                           weekly_stats=weekly_stats,
                           max_daily_cups=max_daily_cups)


@app.route('/add', methods=['POST'])
def add_job():
    feeding_time = request.form['feeding_time']
    portion = request.form.get('portion', DEFAULT_PORTION)
    # Randomize is ON by default; if unchecked, the time is fixed
    is_fixed = request.form.get('randomize') != 'on'
    
    if portion not in PORTION_SIZES:
        portion = DEFAULT_PORTION

    try:
        with open('feeding_schedules.txt', 'r') as file:
            existing_lines = file.readlines()
        
        for line in existing_lines:
            line = line.strip()
            if not line:
                continue
            existing_time = line.split(',')[0]
            if existing_time == feeding_time:
                if wants_json():
                    return jsonify({'success': False, 'message': 'Feeding time already exists'}), 409
                return "Feeding time already exists. <a href='/'>Go back</a>", 400

        # Write the feeding time
        with open('feeding_schedules.txt', 'a') as file:
            if is_fixed:
                file.write(f"{feeding_time},{portion},fixed\n")
            else:
                file.write(f"{feeding_time},{portion}\n")
            file.flush()

        # Also add to today's schedule with randomization applied
        todays_schedule = load_todays_schedule() or []
        existing_times = [datetime.strptime(s['actual_time'], "%H:%M") for s in todays_schedule]
        
        if is_fixed:
            actual_time = feeding_time
        else:
            # Apply randomization (±30 minutes)
            actual_time = apply_random_offset(feeding_time, 30, existing_times)
        
        todays_schedule.append({
            'base_time': feeding_time,
            'actual_time': actual_time,
            'portion': portion,
            'is_fixed': is_fixed,
            'randomized': actual_time != feeding_time
        })
        save_todays_schedule(todays_schedule)

        feeding_time_12h = datetime.strptime(feeding_time, "%H:%M").strftime("%I:%M %p")
        actual_time_12h = datetime.strptime(actual_time, "%H:%M").strftime("%I:%M %p")
        
        if is_fixed:
            logging.info(f"Added feeding time: {feeding_time_12h} ({portion} portion) (fixed)")
        else:
            logging.info(f"Added feeding time: {feeding_time_12h} → {actual_time_12h} ({portion} portion)")

        if wants_json():
            return jsonify({'success': True, 'message': f'Added {feeding_time_12h} feeding'})
        return redirect('/')

    except Exception as e:
        logging.error(f"Error writing to feeding_schedules.txt: {str(e)}")
        if wants_json():
            return jsonify({'success': False, 'message': 'Error adding feeding time'}), 500
        return "An error occurred while adding the feeding time.", 500


@app.route('/delete', methods=['POST'])
def delete_job():
    base_time = request.form['base_time']
    try:
        with open('feeding_schedules.txt', 'r') as file:
            lines = file.readlines()
        with open('feeding_schedules.txt', 'w') as file:
            for line in lines:
                line_time = line.strip().split(',')[0]
                if line_time != base_time:
                    file.write(line)

        # Also remove from today's schedule
        todays_schedule = load_todays_schedule() or []
        todays_schedule = [s for s in todays_schedule if s['base_time'] != base_time]
        save_todays_schedule(todays_schedule)

        logging.info(f"Deleted feeding time: {base_time}")
        if wants_json():
            return jsonify({'success': True, 'message': 'Feeding deleted'})
        return redirect('/')
    except Exception as e:
        logging.error(f"Error deleting feeding time: {str(e)}")
        if wants_json():
            return jsonify({'success': False, 'message': 'Error deleting feeding time'}), 500
        return "An error occurred while deleting the feeding time.", 500


@app.route('/toggle_fixed', methods=['POST'])
def toggle_fixed():
    """Toggle the fixed status of a feeding time."""
    base_time = request.form['base_time']
    try:
        with open('feeding_schedules.txt', 'r') as file:
            lines = file.readlines()
        
        new_lines = []
        new_is_fixed = None
        portion = DEFAULT_PORTION
        
        for line in lines:
            parts = line.strip().split(',')
            if parts[0] == base_time:
                time_str = parts[0]
                portion = parts[1] if len(parts) > 1 and parts[1] not in ['fixed'] else DEFAULT_PORTION
                is_fixed = len(parts) > 2 and parts[2].lower() == 'fixed'
                
                # Toggle fixed status
                if is_fixed:
                    new_lines.append(f"{time_str},{portion}\n")
                    new_is_fixed = False
                else:
                    new_lines.append(f"{time_str},{portion},fixed\n")
                    new_is_fixed = True
            else:
                new_lines.append(line if line.endswith('\n') else line + '\n')
        
        with open('feeding_schedules.txt', 'w') as file:
            file.writelines(new_lines)
        
        # Update today's schedule
        if new_is_fixed is not None:
            todays_schedule = load_todays_schedule() or []
            existing_times = [datetime.strptime(s['actual_time'], "%H:%M") 
                           for s in todays_schedule if s['base_time'] != base_time]
            
            # Remove old entry
            todays_schedule = [s for s in todays_schedule if s['base_time'] != base_time]
            
            # Add updated entry
            if new_is_fixed:
                actual_time = base_time
            else:
                actual_time = apply_random_offset(base_time, 30, existing_times)
            
            todays_schedule.append({
                'base_time': base_time,
                'actual_time': actual_time,
                'portion': portion,
                'is_fixed': new_is_fixed,
                'randomized': actual_time != base_time
            })
            save_todays_schedule(todays_schedule)

        status = 'fixed' if new_is_fixed else 'randomized'
        if wants_json():
            return jsonify({'success': True, 'message': f'Feeding set to {status}'})
        return redirect('/')
    except Exception as e:
        logging.error(f"Error toggling fixed status: {str(e)}")
        if wants_json():
            return jsonify({'success': False, 'message': 'Error toggling fixed status'}), 500
        return "An error occurred.", 500


@app.route('/update_portion', methods=['POST'])
def update_portion():
    """Update the portion size for an existing feeding time."""
    base_time = request.form['base_time']
    new_portion = request.form.get('portion', DEFAULT_PORTION)
    
    if new_portion not in PORTION_SIZES:
        new_portion = DEFAULT_PORTION
    
    try:
        with open('feeding_schedules.txt', 'r') as file:
            lines = file.readlines()
        
        new_lines = []
        for line in lines:
            parts = line.strip().split(',')
            if parts[0] == base_time:
                time_str = parts[0]
                is_fixed = len(parts) > 2 and parts[2].lower() == 'fixed'
                
                if is_fixed:
                    new_lines.append(f"{time_str},{new_portion},fixed\n")
                else:
                    new_lines.append(f"{time_str},{new_portion}\n")
            else:
                new_lines.append(line if line.endswith('\n') else line + '\n')
        
        with open('feeding_schedules.txt', 'w') as file:
            file.writelines(new_lines)
        
        logging.info(f"Updated portion for {base_time} to {new_portion}")
        if wants_json():
            return jsonify({'success': True, 'message': f'Portion updated to {new_portion}'})
        return redirect('/')
    except Exception as e:
        logging.error(f"Error updating portion: {str(e)}")
        if wants_json():
            return jsonify({'success': False, 'message': 'Error updating portion'}), 500
        return "An error occurred.", 500


@app.route('/feed', methods=['POST'])
def trigger_feeding():
    portion = request.form.get('portion', DEFAULT_PORTION)
    
    if portion not in PORTION_SIZES:
        portion = DEFAULT_PORTION
    
    feed_pet(portion=portion)
    logging.info(f"Manual feeding triggered ({portion} portion)")
    if wants_json():
        return jsonify({'success': True, 'message': f'Dispensed {portion} portion'})
    return redirect('/')


@app.route('/sw.js')
def service_worker():
    """Serve service worker from root scope."""
    return app.send_static_file('sw.js'), 200, {
        'Content-Type': 'application/javascript',
        'Service-Worker-Allowed': '/'
    }


def main():
    schedule_thread = Thread(target=run_schedule)
    schedule_thread.start()
    logging.info(f"Starting web interface on port {WEB_PORT}")
    app.run(host='0.0.0.0', port=WEB_PORT, debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true')


if __name__ == '__main__':
    main()
