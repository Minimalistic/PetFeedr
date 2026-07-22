"""Shared core: logging, feeding, and schedule generation.

Imported by both the scheduler entry point (PetFeedr.py) and the web
interface — a plain module avoids the double-import trap of importing
the entry script itself (which would run twice as __main__ and PetFeedr).
"""

import os
import random
import json
import schedule
import logging
import threading
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, timedelta, date
from servo_controller import trigger_servo, PORTION_SIZES, DEFAULT_PORTION
import notify

# One lock for everything that touches the schedule files, the job registry,
# or the motor. The `schedule` library has no thread safety of its own, and
# Flask request threads mutate state while the main loop runs jobs. RLock:
# resync_today() runs pending jobs, and feed_pet re-acquires under it.
STATE_LOCK = threading.RLock()

# App logger: owns feeding_log.txt. propagate=False keeps werkzeug/root
# noise out of the feed log; root still gets a console handler so HTTP
# access lines reach stderr (journald under systemd).
log = logging.getLogger('petfeedr')

LOG_FILE = 'feeding_log.txt'


def setup_logging(console_only=False):
    """Configure the petfeedr logger. Idempotent; called from entry points
    only (not at import) so tests and tooling don't touch the log file.

    console_only: dev/standalone mode — skip the file handler so a second
    process can never race the service's midnight rotation.
    """
    if log.handlers:
        return
    log.setLevel(logging.INFO)
    log.propagate = False
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    log.addHandler(console_handler)

    if not console_only:
        # 'midnight' (not 'D') so rotation aligns with calendar days —
        # the daily stats assume file boundaries fall at 00:00.
        file_handler = TimedRotatingFileHandler(LOG_FILE, when='midnight', backupCount=14)
        file_handler.setFormatter(formatter)
        log.addHandler(file_handler)

    # Root catches everything else (werkzeug) on stderr only.
    logging.basicConfig(level=logging.INFO)

# File to store today's randomized schedule (for web UI display)
TODAYS_SCHEDULE_FILE = 'todays_schedule.json'


def feed_pet(portion=DEFAULT_PORTION, source='scheduled'):
    """Feed the pet with the specified portion size. Returns True on success.

    Locked so a manual feed (Flask thread) can never drive the motor
    concurrently with a scheduled feed (main thread). The servo's
    "Feeding completed" line is the log record the stats parse.

    A dispense failure is the worst failure mode this device has — a
    silently unfed pet — so it pushes a phone notification, not just a log.
    """
    with STATE_LOCK:
        try:
            trigger_servo(portion=portion, source=source)
            return True
        except Exception as e:
            log.exception(f"Feeding failed ({portion} portion, {source}): {e}")
            notify.send(f"Feeding FAILED ({portion} portion, {source}): {e} — "
                        "the motor may be jammed.", priority=1)
            return False


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


def generate_todays_schedule():
    """Read feeding_schedules.txt, roll fresh randomization for non-fixed
    times, and save the result as today's schedule. Does NOT touch the job
    registry — call resync_today() after."""
    # Default randomization range: ±30 minutes
    range_minutes = 30

    with STATE_LOCK:
        if not os.path.isfile('feeding_schedules.txt'):
            open('feeding_schedules.txt', 'w').close()
            log.info("feeding_schedules.txt not found. An empty file has been created.")
            save_todays_schedule([])
            return []

        todays_schedule = []
        scheduled_times = []  # Track times to avoid conflicts

        with open('feeding_schedules.txt', 'r') as file:
            lines = file.readlines()

        if len(lines) == 0:
            log.warning("feeding_schedules.txt is empty. Starting with an empty schedule.")
            save_todays_schedule([])
            return []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            time_str, portion, is_fixed = parse_schedule_line(line)

            # Apply randomization if not fixed
            if not is_fixed:
                actual_time = apply_random_offset(time_str, range_minutes, scheduled_times)
                log.info(f"Randomized: {time_str} → {actual_time} ({portion} portion)")
            else:
                actual_time = time_str
                log.info(f"Fixed time: {actual_time} ({portion} portion)")

            # Track this time for conflict avoidance
            scheduled_times.append(datetime.strptime(actual_time, "%H:%M"))

            # Store for scheduling and web UI display
            todays_schedule.append({
                'base_time': time_str,
                'actual_time': actual_time,
                'portion': portion,
                'is_fixed': is_fixed,
                'randomized': actual_time != time_str
            })

        save_todays_schedule(todays_schedule)
        return todays_schedule


def resync_today():
    """Rebuild the job registry from todays_schedule.json.

    Call after any mutation of today's schedule. run_pending() first: a job
    coming due in the sub-second window before clear() would otherwise be
    silently lost — the library zeroes seconds, so re-registering a time
    that just passed lands tomorrow. Same property is what makes this safe:
    already-fired feedings re-register for tomorrow, never again today.
    """
    with STATE_LOCK:
        schedule.run_pending()
        schedule.clear()
        for entry in load_todays_schedule() or []:
            schedule.every().day.at(entry['actual_time']).do(feed_pet, portion=entry['portion'])


def ensure_today():
    """Startup/day-change entry: reuse today's already-rolled times if the
    file is current — re-randomizing on every restart could re-fire an
    already-dispensed feeding later the same day — else generate fresh.
    Either way, sync the job registry."""
    with STATE_LOCK:
        todays = load_todays_schedule()
        if todays is None:
            todays = generate_todays_schedule()
        resync_today()
        return todays


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
        log.error(f"Error saving today's schedule: {e}")


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
        log.error(f"Error loading today's schedule: {e}")
        return None
