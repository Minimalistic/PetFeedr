"""Shared core: logging, feeding, and schedule generation.

Imported by both the scheduler entry point (PetFeedr.py) and the web
interface — a plain module avoids the double-import trap of importing
the entry script itself (which would run twice as __main__ and PetFeedr).
"""

import os
import random
import re
import json
import schedule
import logging
import threading
import time
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, timedelta, date
from servo_controller import trigger_servo, DEFAULT_PORTION
from DRV8825 import on_raspberry_pi
from feeding_stats import (PORTION_CUPS, COMPLETED_RE, parse_weekly_stats,
                           calculate_consumption_rate, read_all_log_lines)
import hopper
import notify
import events
import schedule_store
from atomicfile import write_atomic

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


def feed_pet(portion=DEFAULT_PORTION, source='scheduled', base_time=None, scheduled_for=None,
             late_by_min=None):
    """Feed the pet with the specified portion size. Returns True on success.

    Locked so a manual feed (Flask thread) can never drive the motor
    concurrently with a scheduled feed (main thread). The servo's
    "Feeding completed" line is the log record the stats parse; the
    event journal gets the same dispense with its numbers (base_time and
    scheduled_for are the schedule's HH:MM pair, None for manual feeds;
    late_by_min is set only by a startup catch-up).

    A dispense failure is the worst failure mode this device has — a
    silently unfed pet — so it pushes a phone notification, not just a log.
    """
    with STATE_LOCK:
        try:
            duration = trigger_servo(portion=portion, source=source)
        except Exception as e:
            log.exception(f"Feeding failed ({portion} portion, {source}): {e}")
            notify.send(f"Feeding FAILED ({portion} portion, {source}): {e} — "
                        "the motor may be jammed.", priority=1)
            events.record('failure', portion=portion, source=source, error=str(e),
                          base_time=base_time, scheduled_for=scheduled_for)
            return False
        cups = PORTION_CUPS.get(portion, 0.25)
        hopper_cups = _track_hopper(cups)
        events.record('dispense', portion=portion, cups=cups, source=source,
                      duration_s=round(duration, 2) if isinstance(duration, (int, float)) else None,
                      base_time=base_time, scheduled_for=scheduled_for,
                      hopper_cups=hopper_cups, late_by_min=late_by_min)
        return True


def _track_hopper(cups):
    """Count the dispense toward hopper level; warn once when running low.
    Returns the counter after this dispense (None if tracking failed).
    Tracking must never break a feeding that already succeeded."""
    try:
        state = hopper.record_dispense(cups)
        rate = calculate_consumption_rate(parse_weekly_stats(), cups_per_lb=hopper.cups_per_lb(state))
        message = hopper.check_low(rate['daily_cups'] if rate else None)
        if message:
            log.info(message)
            notify.send(message)
        return state['cups_since_refill']
    except Exception as e:
        log.warning(f"Hopper tracking failed: {e}")
        return None


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
        entries = schedule_store.read_entries()
        if not entries:
            # A missing or empty schedule means nothing gets fed today. That's
            # never the steady state (a dead SD write, a bad restore), so page.
            if not schedule_store.exists():
                open(schedule_store.SCHEDULES_FILE, 'w').close()
                log.warning(f"{schedule_store.SCHEDULES_FILE} not found. An empty file has been created.")
            else:
                log.warning(f"{schedule_store.SCHEDULES_FILE} is empty. Starting with an empty schedule.")
            notify.send("No feedings are scheduled today — check the feeder's schedule.", priority=1)
            save_todays_schedule([])
            return []

        todays_schedule = []
        scheduled_times = []  # Track times to avoid conflicts

        for entry in entries:
            time_str, portion, is_fixed = entry['time'], entry['portion'], entry['is_fixed']

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


def scheduled_feed(portion, base_time, scheduled_for):
    """Job body for a scheduled slot — dispenses at most once per slot per day.

    The Pi has no battery clock: after a power cut it boots on a saved time
    that can be half an hour stale, then jumps forward when NTP syncs. A
    slot fed just before the outage then looks like it's still ahead, gets
    registered again, and would fire a second time. Checking the record
    first makes the job safe against that and any other re-registration.
    """
    with STATE_LOCK:
        today = date.today()
        status, _ = slot_outcome(scheduled_for, today, *todays_records(today))
        if status:
            log.warning(f"Skipping {scheduled_for} feeding — already recorded as {status} today "
                        "(clock jump or restart)")
            return False
        return feed_pet(portion=portion, base_time=base_time, scheduled_for=scheduled_for)


# systemd-timesyncd creates this on its first sync after boot (/run is tmpfs)
CLOCK_SYNC_FLAG = '/run/systemd/timesync/synchronized'
CLOCK_WAIT_S = 600


def wait_for_clock_sync(timeout_s=CLOCK_WAIT_S, flag=CLOCK_SYNC_FLAG, is_pi=None,
                        sleep=time.sleep, monotonic=time.monotonic):
    """Hold the scheduler until the system clock is NTP-synced. Returns True
    once synced (or off a Pi, where it doesn't apply), False on timeout.

    Scheduling on the stale boot-time clock is what sets up a double feed,
    so wait — but not forever: with no network the pet still has to eat, so
    after timeout_s the feeder runs on the saved time and says so loudly.
    """
    if is_pi is None:
        is_pi = on_raspberry_pi()
    if not is_pi or os.path.exists(flag):
        return True
    log.warning(f"System clock isn't NTP-synced yet (no battery clock on this Pi) — "
                f"holding the scheduler for up to {timeout_s // 60} min")
    started = monotonic()
    while monotonic() - started < timeout_s:
        sleep(5)
        if os.path.exists(flag):
            log.info(f"Clock synced after {int(monotonic() - started)}s — starting the scheduler")
            return True
    log.error("Clock still not synced — scheduling on the saved time, which may be off")
    notify.send("Feeder started without a synced clock (no network?). Feed times may be off "
                "until it syncs.", priority=1)
    return False


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
            schedule.every().day.at(entry['actual_time']).do(
                scheduled_feed, portion=entry['portion'],
                base_time=entry['base_time'], scheduled_for=entry['actual_time'])


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


CATCH_UP_WINDOW_MIN = 60  # later than this, a meal shifts the pet's day — leave it to a human
FED_MATCH_MIN = 2         # a scheduled "completed" line this close to a slot counts as that slot
# Written just before a catch-up dispense; its "completed" line lands late,
# outside FED_MATCH_MIN, so this line is what marks the slot handled in the log
CATCH_UP_RE = re.compile(r'^(?P<date>\d{4}-\d{2}-\d{2}) .* Catching up missed '
                         r'(?P<slot>\d{2}:\d{2}) feeding \((?P<late>\d+) min late\)')


def slot_outcome(actual_time, today, todays_events, log_lines):
    """What happened to one of today's slots: (status, late_min).

    status is 'fed', 'late' (caught up after a restart), 'failed',
    'missed' (too late to catch up), or None when nothing is recorded yet.
    One definition shared by the startup catch-up and the dashboard, so
    what the timeline shows is what the feeder believes.

    The journal is checked first; the log is the fallback because journal
    writes are fail-soft, and a missing event must never turn into a
    second meal.
    """
    found = {}
    for e in todays_events:
        if e.get('scheduled_for') == actual_time:
            found.setdefault(e.get('event'), e)
    if 'dispense' in found:
        late = found['dispense'].get('late_by_min')
        return ('late', late) if late else ('fed', None)
    if 'failure' in found:
        return 'failed', None
    if 'missed' in found:
        return 'missed', found['missed'].get('late_by_min')

    for line in log_lines:
        m = CATCH_UP_RE.match(line)
        if m and m['date'] == today.isoformat() and m['slot'] == actual_time:
            return 'late', int(m['late'])
    slot = datetime.combine(today, datetime.strptime(actual_time, "%H:%M").time())
    for line in log_lines:
        m = COMPLETED_RE.match(line.strip())
        if not m or m['date'] != today.isoformat() or m['source'] == 'manual':
            continue
        fed_at = datetime.strptime(f"{m['date']} {m['time']}", "%Y-%m-%d %H:%M:%S")
        if abs(fed_at - slot) <= timedelta(minutes=FED_MATCH_MIN):
            return 'fed', None
    return None, None


def todays_records(today):
    """(today's journal events, all log lines) — the inputs slot_outcome reads."""
    todays_events = [e for e in events.read_all() if e.get('ts', '').startswith(today.isoformat())]
    return todays_events, read_all_log_lines()


def catch_up_missed(now=None):
    """Startup: dispense today's feedings that came due while the process
    was down (restart, deploy, power blip). resync_today() re-registers a
    passed time for tomorrow, so without this a restart at 07:02 silently
    skips breakfast. Only within CATCH_UP_WINDOW_MIN; older misses are
    logged and left to the mini's watchdog, which pages about them.
    Returns the list of actual_times that were caught up."""
    now = now or datetime.now()
    today = now.date()
    caught_up = []
    with STATE_LOCK:
        todays_events, log_lines = todays_records(today)
        for entry in load_todays_schedule() or []:
            slot = datetime.combine(today, datetime.strptime(entry['actual_time'], "%H:%M").time())
            late = now - slot
            # Any recorded outcome — including a failure or an earlier
            # catch-up attempt — means hands off: never a second meal
            if late <= timedelta(0) or slot_outcome(
                    entry['actual_time'], today, todays_events, log_lines)[0]:
                continue
            late_min = int(late.total_seconds() // 60)
            if late > timedelta(minutes=CATCH_UP_WINDOW_MIN):
                log.warning(f"Missed {entry['actual_time']} feeding ({late_min} min ago) — "
                            "too late to catch up automatically")
                # Recorded so the dashboard and streak show the miss honestly
                events.record('missed', portion=entry['portion'], base_time=entry['base_time'],
                              scheduled_for=entry['actual_time'], late_by_min=late_min)
                continue
            log.info(f"Catching up missed {entry['actual_time']} feeding ({late_min} min late)")
            if feed_pet(portion=entry['portion'], base_time=entry['base_time'],
                        scheduled_for=entry['actual_time'], late_by_min=late_min):
                caught_up.append(entry['actual_time'])
                notify.send(f"Caught up the {entry['actual_time']} feeding {late_min} min late "
                            "after a restart.", priority=-1)
    return caught_up


def save_todays_schedule(schedule_data):
    """Save today's randomized schedule for web UI display."""
    data = {
        'date': date.today().isoformat(),
        'schedule': schedule_data
    }
    try:
        write_atomic(TODAYS_SCHEDULE_FILE, json.dumps(data, indent=2))
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
