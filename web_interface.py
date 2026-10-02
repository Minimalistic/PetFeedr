#!/usr/bin/env python3

import os
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from flask import Flask, request, render_template, jsonify

from feeder_core import feed_pet, STATE_LOCK, log, setup_logging
from feeding_stats import day_feedings, PORTION_CUPS
import manual_limit
from servo_controller import PORTION_SIZES, DEFAULT_PORTION
from responses import wants_json, error_response, success_response
from schedule_routes import schedule_bp
import hopper
import view_state
MAX_REFILL_LBS = 50  # sanity bound — a typo like 700 would wreck the cups-per-lb median

# Cooldown between manual feeds (limits live in manual_limit.py). Monotonic
# stamp; in-memory is fine — a restart is a natural reset
_last_manual_feed = None

# Configurable port - default 5000, override with PETFEEDR_PORT env var
WEB_PORT = int(os.environ.get('PETFEEDR_PORT', 5000))

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(24).hex())
# Revalidate static files on every load (a 304 on the LAN). Without it,
# browsers heuristically cache the JS modules and could keep running the
# previous release after a deploy
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.register_blueprint(schedule_bp)


@app.before_request
def reject_cross_origin_posts():
    """CSRF guard: the UI has no auth, so any web page open on a LAN device
    could otherwise POST /feed. Browsers always send Origin on cross-origin
    POSTs; a missing Origin (curl, scripts) is let through."""
    if request.method != 'POST':
        return None
    origin = request.headers.get('Origin')
    if origin and urlparse(origin).netloc != request.host:
        log.warning(f"Rejected cross-origin POST {request.path} from {origin}")
        return error_response('Cross-origin request refused', 403)
    return None


@app.route('/')
def index():
    """The page is a shell plus the first state snapshot; static/js renders
    every card from it and keeps it current without reloading."""
    return render_template('index.html',
                           initial_state=view_state.build(),
                           asset_version=view_state.ASSET_VERSION)


@app.route('/api/state')
def api_state():
    """Current dashboard state. Polled by the open page; read-only."""
    return jsonify({'success': True, 'data': view_state.build()})


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
    global _last_manual_feed
    portion = request.form.get('portion', DEFAULT_PORTION)

    if portion not in PORTION_SIZES:
        portion = DEFAULT_PORTION

    # Check-and-dispense under the lock so two racing requests can't both pass
    with STATE_LOCK:
        # None, not 0.0: monotonic() can start near zero, which would refuse
        # every feed for the first minute after boot
        since_last = None if _last_manual_feed is None else time.monotonic() - _last_manual_feed
        if since_last is not None and since_last < manual_limit.COOLDOWN_S:
            return error_response(
                f'Just fed — try again in {int(manual_limit.COOLDOWN_S - since_last) + 1}s', 429)
        manual_cups = manual_limit.used_today_cups()
        allowance = manual_limit.allowance_cups()
        if manual_cups + PORTION_CUPS[portion] > allowance:
            log.warning(f"Manual feed refused: {manual_cups:g} of {allowance:g} manual cups used today")
            return error_response(
                f'Manual limit reached — {manual_cups:g} of {allowance:g} cups used today '
                '(resets at midnight)', 429)

        # No separate "Manual feeding triggered" line — the servo's completed
        # line carries the source, and a second line would double-count in stats
        ok = feed_pet(portion=portion, source='manual')
        if ok:
            _last_manual_feed = time.monotonic()

    if ok:
        return success_response(f'Dispensed {portion} portion')
    return error_response('Feeding failed — check the feeder', 500)


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
    return success_response(message)


@app.route('/sw.js')
def service_worker():
    """Serve service worker from root scope."""
    # The asset version is stamped into the worker so every deploy changes
    # its bytes: browsers install the new worker and drop the old cache
    # without anyone bumping a cache name by hand
    body = (Path(app.static_folder) / 'sw.js').read_text().replace(
        '__ASSET_VERSION__', view_state.ASSET_VERSION)
    return body, 200, {
        'Content-Type': 'application/javascript',
        'Cache-Control': 'no-cache',
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
