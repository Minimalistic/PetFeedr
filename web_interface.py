#!/usr/bin/env python3

import os
from feeder_core import (feed_pet, load_todays_schedule, save_todays_schedule,
                         apply_random_offset, resync_today, STATE_LOCK, log, setup_logging)
from feeding_stats import (parse_recent_activity, parse_weekly_stats, build_week_summary,
                           calculate_consumption_rate, calculate_daily_total, day_feedings)
from servo_controller import PORTION_SIZES, DEFAULT_PORTION
from DRV8825 import SIMULATION_MODE

APP_VERSION = "1.1.0"

# Configurable port - default 5000, override with PETFEEDR_PORT env var
WEB_PORT = int(os.environ.get('PETFEEDR_PORT', 5000))
from datetime import datetime
from flask import Flask, redirect, url_for, request, render_template, jsonify

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
            log.error(f"Error parsing time: {time_str}")
            continue
    
    # Sort by actual time
    schedules.sort(key=lambda x: x['sort_key'])
    
    return schedules


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


@app.route('/')
def index():
    schedules = read_schedules_with_details()
    schedules = mark_past_feedings(schedules)
    
    daily_total = calculate_daily_total(schedules)
    next_feeding = get_next_feeding(schedules)
    recent_activity = parse_recent_activity(days=1, limit=1)
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
    for mins in range(first_hour, timeline_end, 60):
        h = mins // 60
        pct = ((mins - timeline_start) / (timeline_end - timeline_start)) * 100
        show_label = (h % 2 == 0)
        label = f"{h % 12 or 12}{'AM' if h < 12 else 'PM'}" if show_label else None
        timeline_hours.append({'label': label, 'pct': pct})

    # Weekly stats
    weekly_stats = parse_weekly_stats()
    max_daily_cups = max((d['total_cups'] for d in weekly_stats), default=0.5)
    max_daily_cups = max(max_daily_cups, 0.5)
    week_summary = build_week_summary(weekly_stats)
    consumption = calculate_consumption_rate(weekly_stats)

    portion_info = {name: desc for name, (cycles, desc) in PORTION_SIZES.items()}

    return render_template('index.html',
                           schedules=schedules,
                           next_feeding=next_feeding,
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
                           max_daily_cups=max_daily_cups,
                           week_summary=week_summary,
                           consumption=consumption)


@app.route('/api/day-detail/<date_str>')
def day_detail(date_str):
    """Return feeding details for a specific date (YYYY-MM-DD)."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid date format'}), 400

    feedings, total_cups = day_feedings(date_str)
    return jsonify({
        'success': True,
        'date': date_str,
        'feedings': feedings,
        'total_cups': total_cups,
        'total_feedings': len(feedings)
    })


@app.route('/add', methods=['POST'])
def add_job():
    feeding_time = request.form['feeding_time']
    portion = request.form.get('portion', DEFAULT_PORTION)
    # Randomize is ON by default; if unchecked, the time is fixed
    is_fixed = request.form.get('randomize') != 'on'
    
    if portion not in PORTION_SIZES:
        portion = DEFAULT_PORTION

    try:
        with STATE_LOCK:
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
            resync_today()

        feeding_time_12h = datetime.strptime(feeding_time, "%H:%M").strftime("%I:%M %p")
        actual_time_12h = datetime.strptime(actual_time, "%H:%M").strftime("%I:%M %p")
        
        if is_fixed:
            log.info(f"Added feeding time: {feeding_time_12h} ({portion} portion) (fixed)")
        else:
            log.info(f"Added feeding time: {feeding_time_12h} → {actual_time_12h} ({portion} portion)")

        if wants_json():
            return jsonify({'success': True, 'message': f'Added {feeding_time_12h} feeding'})
        return redirect('/')

    except Exception as e:
        log.error(f"Error writing to feeding_schedules.txt: {str(e)}")
        if wants_json():
            return jsonify({'success': False, 'message': 'Error adding feeding time'}), 500
        return "An error occurred while adding the feeding time.", 500


@app.route('/delete', methods=['POST'])
def delete_job():
    base_time = request.form['base_time']
    try:
        with STATE_LOCK:
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
            resync_today()

        log.info(f"Deleted feeding time: {base_time}")
        if wants_json():
            return jsonify({'success': True, 'message': 'Feeding deleted'})
        return redirect('/')
    except Exception as e:
        log.error(f"Error deleting feeding time: {str(e)}")
        if wants_json():
            return jsonify({'success': False, 'message': 'Error deleting feeding time'}), 500
        return "An error occurred while deleting the feeding time.", 500


@app.route('/toggle_fixed', methods=['POST'])
def toggle_fixed():
    """Toggle the fixed status of a feeding time."""
    base_time = request.form['base_time']
    try:
        with STATE_LOCK:
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
                resync_today()

        status = 'fixed' if new_is_fixed else 'randomized'
        if wants_json():
            return jsonify({'success': True, 'message': f'Feeding set to {status}'})
        return redirect('/')
    except Exception as e:
        log.error(f"Error toggling fixed status: {str(e)}")
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
        with STATE_LOCK:
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

            # Keep today's schedule in step so the already-registered job
            # dispenses the new portion today, not tomorrow
            todays_schedule = load_todays_schedule() or []
            for entry in todays_schedule:
                if entry['base_time'] == base_time:
                    entry['portion'] = new_portion
            save_todays_schedule(todays_schedule)
            resync_today()

        log.info(f"Updated portion for {base_time} to {new_portion}")
        if wants_json():
            return jsonify({'success': True, 'message': f'Portion updated to {new_portion}'})
        return redirect('/')
    except Exception as e:
        log.error(f"Error updating portion: {str(e)}")
        if wants_json():
            return jsonify({'success': False, 'message': 'Error updating portion'}), 500
        return "An error occurred.", 500


@app.route('/feed', methods=['POST'])
def trigger_feeding():
    portion = request.form.get('portion', DEFAULT_PORTION)
    
    if portion not in PORTION_SIZES:
        portion = DEFAULT_PORTION
    
    # No separate "Manual feeding triggered" line — the servo's completed
    # line carries the source, and a second line would double-count in stats
    feed_pet(portion=portion, source='manual')
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
    """Standalone dev entry — UI only, no scheduler. Console-only logging so
    a dev instance can never race the service's log rotation."""
    setup_logging(console_only=True)
    log.info(f"Starting web interface (standalone dev) on port {WEB_PORT}")
    app.run(host='0.0.0.0', port=WEB_PORT, debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true')


if __name__ == '__main__':
    main()
