"""Schedule-editing routes: add, delete, toggle fixed, change portion.

Each writes feeding_schedules.txt and today's schedule under STATE_LOCK,
then resyncs the job registry so the edit takes effect immediately.
"""

from datetime import datetime
from flask import Blueprint, redirect, request, jsonify

from feeder_core import (load_todays_schedule, save_todays_schedule,
                         apply_random_offset, resync_today, STATE_LOCK, log)
from responses import wants_json, error_response
from servo_controller import PORTION_SIZES, DEFAULT_PORTION
import schedule_store

# Blueprint: keeps this group in its own file while URLs stay unchanged
schedule_bp = Blueprint('schedule', __name__)


def valid_hhmm(value):
    """Strict zero-padded HH:MM — the scheduler and the file format both assume it."""
    try:
        return datetime.strptime(value, "%H:%M").strftime("%H:%M") == value
    except (TypeError, ValueError):
        return False


def replace_today_entry(base_time, portion, is_fixed):
    """Re-roll one entry in today's schedule (or add it). Caller holds STATE_LOCK."""
    todays_schedule = [s for s in load_todays_schedule() or [] if s['base_time'] != base_time]
    if is_fixed:
        actual_time = base_time
    else:
        existing_times = [datetime.strptime(s['actual_time'], "%H:%M") for s in todays_schedule]
        actual_time = apply_random_offset(base_time, 30, existing_times)
    todays_schedule.append({
        'base_time': base_time,
        'actual_time': actual_time,
        'portion': portion,
        'is_fixed': is_fixed,
        'randomized': actual_time != base_time
    })
    save_todays_schedule(todays_schedule)
    resync_today()
    return actual_time


@schedule_bp.route('/add', methods=['POST'])
def add_job():
    feeding_time = request.form.get('feeding_time', '')
    portion = request.form.get('portion', DEFAULT_PORTION)
    # Randomize is ON by default; if unchecked, the time is fixed
    is_fixed = request.form.get('randomize') != 'on'

    if portion not in PORTION_SIZES:
        portion = DEFAULT_PORTION
    # A malformed time in the file would crash tomorrow's schedule generation
    if not valid_hhmm(feeding_time):
        return error_response('Feeding time must be HH:MM', 400)

    try:
        with STATE_LOCK:
            entries = schedule_store.read_entries()
            if any(e['time'] == feeding_time for e in entries):
                return error_response('Feeding time already exists', 409)
            entries.append({'time': feeding_time, 'portion': portion, 'is_fixed': is_fixed})
            schedule_store.write_entries(entries)
            actual_time = replace_today_entry(feeding_time, portion, is_fixed)

        feeding_time_12h = datetime.strptime(feeding_time, "%H:%M").strftime("%I:%M %p").lstrip("0")
        actual_time_12h = datetime.strptime(actual_time, "%H:%M").strftime("%I:%M %p").lstrip("0")

        if is_fixed:
            log.info(f"Added feeding time: {feeding_time_12h} ({portion} portion) (fixed)")
        else:
            log.info(f"Added feeding time: {feeding_time_12h} → {actual_time_12h} ({portion} portion)")

        if wants_json():
            return jsonify({'success': True, 'message': f'Added {feeding_time_12h} feeding'})
        return redirect('/')

    except Exception as e:
        log.error(f"Error adding feeding time: {e}")
        return error_response('Error adding feeding time', 500)


@schedule_bp.route('/delete', methods=['POST'])
def delete_job():
    base_time = request.form.get('base_time', '')
    try:
        with STATE_LOCK:
            entries = schedule_store.read_entries()
            schedule_store.write_entries([e for e in entries if e['time'] != base_time])

            todays_schedule = [s for s in load_todays_schedule() or [] if s['base_time'] != base_time]
            save_todays_schedule(todays_schedule)
            resync_today()

        log.info(f"Deleted feeding time: {base_time}")
        if wants_json():
            return jsonify({'success': True, 'message': 'Feeding deleted'})
        return redirect('/')
    except Exception as e:
        log.error(f"Error deleting feeding time: {e}")
        return error_response('Error deleting feeding time', 500)


@schedule_bp.route('/toggle_fixed', methods=['POST'])
def toggle_fixed():
    """Toggle the fixed status of a feeding time."""
    base_time = request.form.get('base_time', '')
    try:
        with STATE_LOCK:
            entries = schedule_store.read_entries()
            target = next((e for e in entries if e['time'] == base_time), None)
            if target is None:
                return error_response('Feeding time not found', 404)
            target['is_fixed'] = not target['is_fixed']
            schedule_store.write_entries(entries)
            replace_today_entry(base_time, target['portion'], target['is_fixed'])

        status = 'fixed' if target['is_fixed'] else 'randomized'
        if wants_json():
            return jsonify({'success': True, 'message': f'Feeding set to {status}'})
        return redirect('/')
    except Exception as e:
        log.error(f"Error toggling fixed status: {e}")
        return error_response('Error toggling fixed status', 500)


@schedule_bp.route('/update_portion', methods=['POST'])
def update_portion():
    """Update the portion size for an existing feeding time."""
    base_time = request.form.get('base_time', '')
    new_portion = request.form.get('portion', DEFAULT_PORTION)

    if new_portion not in PORTION_SIZES:
        new_portion = DEFAULT_PORTION

    try:
        with STATE_LOCK:
            entries = schedule_store.read_entries()
            for entry in entries:
                if entry['time'] == base_time:
                    entry['portion'] = new_portion
            schedule_store.write_entries(entries)

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
        log.error(f"Error updating portion: {e}")
        return error_response('Error updating portion', 500)
