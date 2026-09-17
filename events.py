"""Append-only event journal: feeding_events.jsonl.

feeding_log.txt is a human log that rotates away after 14 days, so it can't
be the analysis record. This file is the durable one: one JSON object per
line, never rotated (a few events a day is well under 200KB a year), pulled
off the Pi by the mini for long-term stats.

Event kinds and their fields:
  dispense    portion, cups, source, duration_s, base_time, scheduled_for,
              hopper_cups (counter after this dispense)
  failure     portion, source, error
  refill      remaining_pct, cups_before, capacity_estimate, capacity,
              lbs_added, cups_per_lb_estimate, capacity_lbs_estimate
              (all null when not weighed)
  hopper_low  level, days_left

Every event carries ts (local ISO time) and sim (True on a dev box without
GPIO) so simulated runs can be filtered out of real analysis.

Writing must never break the feeding that produced it — failures are
logged as warnings, not raised. Callers hold feeder_core.STATE_LOCK.
"""

import json
import logging
from datetime import datetime
from DRV8825 import SIMULATION_MODE

log = logging.getLogger('petfeedr')

EVENTS_FILE = 'feeding_events.jsonl'


def record(kind, **fields):
    entry = {'ts': datetime.now().isoformat(timespec='seconds'), 'event': kind}
    if SIMULATION_MODE:
        entry['sim'] = True
    entry.update(fields)
    try:
        with open(EVENTS_FILE, 'a') as f:
            f.write(json.dumps(entry) + '\n')
    except (OSError, TypeError, ValueError) as e:  # TypeError: an unserializable field must not break a feeding
        log.warning(f"Event journal write failed ({kind}): {e}")


def read_all():
    """All events, oldest first. Malformed lines are skipped with a warning."""
    events = []
    try:
        with open(EVENTS_FILE) as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    log.warning(f"Skipping malformed event on line {lineno}")
    except FileNotFoundError:
        pass
    return events
