#!/usr/bin/env python3

import os
from datetime import datetime
from flask import Flask, redirect, request, render_template, jsonify

from feeder_core import feed_pet, STATE_LOCK, log, setup_logging
from feeding_stats import day_feedings
from servo_controller import PORTION_SIZES, DEFAULT_PORTION
from DRV8825 import SIMULATION_MODE
from responses import wants_json, error_response
from schedule_routes import schedule_bp
import dashboard
import hopper

APP_VERSION = "1.3.1"
MAX_REFILL_LBS = 50  # sanity bound — a typo like 700 would wreck the cups-per-lb median

# Configurable port - default 5000, override with PETFEEDR_PORT env var
WEB_PORT = int(os.environ.get('PETFEEDR_PORT', 5000))

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(24).hex())
app.register_blueprint(schedule_bp)


# Custom Jinja2 filter for formatting datetime objects
@app.template_filter('strftime')
def _jinja2_filter_datetime(value, format=None):
    return value


@app.route('/')
def index():
    return render_template('index.html',
                           portion_sizes=PORTION_SIZES,
                           default_portion=DEFAULT_PORTION,
                           simulation_mode=SIMULATION_MODE,
                           app_version=APP_VERSION,
                           **dashboard.index_context())


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


@app.route('/feed', methods=['POST'])
def trigger_feeding():
    portion = request.form.get('portion', DEFAULT_PORTION)

    if portion not in PORTION_SIZES:
        portion = DEFAULT_PORTION

    # No separate "Manual feeding triggered" line — the servo's completed
    # line carries the source, and a second line would double-count in stats
    ok = feed_pet(portion=portion, source='manual')
    if wants_json():
        if ok:
            return jsonify({'success': True, 'message': f'Dispensed {portion} portion'})
        return jsonify({'success': False, 'message': 'Feeding failed — check the feeder'}), 500
    return redirect('/')


@app.route('/refill', methods=['POST'])
def refill():
    """Record a hopper refill with a rough estimate of what was left."""
    try:
        remaining_pct = float(request.form.get('remaining_pct', ''))
    except ValueError:
        if wants_json():
            return jsonify({'success': False, 'message': 'Invalid percentage'}), 400
        return "Invalid percentage", 400
    if not 0 <= remaining_pct <= 95:
        if wants_json():
            return jsonify({'success': False, 'message': 'Percentage must be between 0 and 95'}), 400
        return "Percentage must be between 0 and 95", 400

    # Weight is optional — blank means "didn't weigh it", not an error
    lbs_raw = request.form.get('lbs_added', '').strip()
    lbs_added = None
    if lbs_raw:
        try:
            lbs_added = float(lbs_raw)
        except ValueError:
            lbs_added = -1  # falls through to the range check below
        if not 0 < lbs_added <= MAX_REFILL_LBS:
            message = f'Pounds added must be between 0 and {MAX_REFILL_LBS}'
            if wants_json():
                return jsonify({'success': False, 'message': message}), 400
            return message, 400

    with STATE_LOCK:
        state = hopper.record_refill(remaining_pct, lbs_added)
    capacity = hopper.capacity_cups(state)
    log.info(f"Hopper refilled (was ~{remaining_pct:.0f}% full"
             + (f", {lbs_added:g} lb added)" if lbs_added else ")"))

    if capacity:
        message = f'Refill recorded — hopper holds ~{capacity} cups'
    else:
        message = 'Refill recorded'
    if wants_json():
        return jsonify({'success': True, 'message': message})
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
