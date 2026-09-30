#!/usr/bin/env python3
"""Outside-in watchdog for the feeder, run on the mini after every sync.

The Pi can page about failures it can see (a motor exception). It can't
page about its own death, a stopped service, or a meal that never fired —
that takes a second machine. This reads the store the sync just refreshed
and pushes a Pushover alert for:

  unreachable   no successful sync in UNREACHABLE_MIN (and "back online" after)
  stale         the Pi never rolled today's schedule over — service likely down
  missed        a scheduled feeding with no dispense event MISSED_GRACE_MIN later
  simulation    the Pi journal has sim events — RPi.GPIO failed, motor isn't driven

Each alert fires once (keyed in watchdog_state.json). Stdlib only.

Usage: watchdog.py <store>   (creds: PUSHOVER_TOKEN / PUSHOVER_USER in env)
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

UNREACHABLE_MIN = 45   # three missed 15-min syncs — rides out a Wi-Fi blip
FRESH_MIN = 20         # schedule checks only trust data this recent
MISSED_GRACE_MIN = 15  # a dispense lands within seconds; 15 min is generous
ROLLOVER_GRACE_MIN = 15

PUSHOVER_URL = 'https://api.pushover.net/1/messages.json'


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        print(f"watchdog: {path} unreadable ({e})")
        return default


def load_events(path):
    events = []
    try:
        with open(path) as f:
            for line in f:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # a torn last line from a mid-write copy
    except FileNotFoundError:
        pass
    return events


def check(store, now, last_contact):
    """Pure: (key, message, priority) alerts that apply right now, plus
    whether the Pi is currently considered reachable."""
    alerts = []
    since_contact = now - last_contact if last_contact else None
    reachable = since_contact is not None and since_contact < timedelta(minutes=UNREACHABLE_MIN)
    if not reachable:
        when = last_contact.strftime('%b %d %H:%M') if last_contact else 'never'
        alerts.append(('unreachable', f"Feeder unreachable — last sync {when}. "
                       "Power, Wi-Fi, or the SD card.", 0))
    if since_contact is None or since_contact > timedelta(minutes=FRESH_MIN):
        return alerts, reachable

    today = now.date().isoformat()
    events = load_events(os.path.join(store, 'feeding_events.jsonl'))

    if any(e.get('sim') and e.get('ts', '').startswith(today) for e in events):
        alerts.append((f'sim:{today}', "Feeder is running in SIMULATION mode — the motor "
                       "isn't being driven. RPi.GPIO is missing or broken on the Pi.", 1))

    todays = load_json(os.path.join(store, 'todays_schedule.json'), {})
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if todays.get('date') != today:
        if now - midnight > timedelta(minutes=ROLLOVER_GRACE_MIN):
            alerts.append((f'stale:{today}', "Feeder didn't start today's schedule — "
                           "the PetFeedr service is probably stopped.", 1))
        return alerts, reachable

    fired = {e.get('scheduled_for') for e in events
             if e.get('event') in ('dispense', 'failure') and e.get('ts', '').startswith(today)}
    for entry in todays.get('schedule', []):
        due = datetime.combine(now.date(), datetime.strptime(entry['actual_time'], '%H:%M').time())
        if now - due < timedelta(minutes=MISSED_GRACE_MIN) or entry['actual_time'] in fired:
            continue
        # A failure event already paged from the Pi, so only silence is missed
        alerts.append((f"missed:{today}:{entry['actual_time']}",
                       f"No {entry['portion']} feeding recorded for {entry['actual_time']} "
                       "(if you added that time after it passed, ignore this).", 1))
    return alerts, reachable


def send(message, priority):
    token, user = os.environ.get('PUSHOVER_TOKEN'), os.environ.get('PUSHOVER_USER')
    if not token or not user:
        print(f"watchdog: UNSENT (no Pushover creds): {message}")
        return False
    data = urllib.parse.urlencode({'token': token, 'user': user, 'title': 'PetFeedr watchdog',
                                   'message': message, 'priority': priority}).encode()
    try:
        with urllib.request.urlopen(PUSHOVER_URL, data=data, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"watchdog: Pushover failed ({e}): {message}")
        return False


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    store = sys.argv[1]
    now = datetime.now()
    state_path = os.path.join(store, 'watchdog_state.json')
    state = load_json(state_path, {'sent': []})

    try:
        with open(os.path.join(store, 'last_contact')) as f:
            last_contact = datetime.fromtimestamp(int(f.read().strip()))
    except (FileNotFoundError, ValueError):
        last_contact = None

    alerts, reachable = check(store, now, last_contact)

    sent = set(state['sent'])
    if reachable and 'unreachable' in sent:
        if send("Feeder is back online.", 0):
            sent.discard('unreachable')
    for key, message, priority in alerts:
        if key not in sent and send(message, priority):
            sent.add(key)
            print(f"watchdog: alerted {key}")

    # Day-keyed entries only matter today; 'unreachable' persists until recovery
    today = now.date().isoformat()
    state['sent'] = sorted(k for k in sent if k == 'unreachable' or today in k)
    tmp = state_path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f)
    os.replace(tmp, state_path)


if __name__ == '__main__':
    main()
