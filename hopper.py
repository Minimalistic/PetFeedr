"""Hopper level tracking — no sensors, learns capacity from refill feedback.

State lives in hopper.json (runtime file, preserved on the Pi). A counter
tracks cups dispensed since the last refill; when Jason refills and gives a
rough estimate of what was left, each event yields a capacity estimate
(cups dispensed / fraction consumed, assuming refills go to full). The
median of the last few estimates is the working capacity — robust to one
bad guess. Until the first refill event, the hopper is in "learning" mode.

Callers hold feeder_core.STATE_LOCK; this module does plain file I/O.
"""

import json
import logging
from datetime import date
from statistics import median

log = logging.getLogger('petfeedr')

HOPPER_FILE = 'hopper.json'
ESTIMATES_KEPT = 5
LOW_DAYS = 2       # alert when predicted days of food left drops to this
LOW_LEVEL = 0.15   # ...or when estimated fill level drops below this


def _default_state():
    # A fresh file assumes the hopper was just filled — true at first deploy
    return {
        'last_refill': date.today().isoformat(),
        'cups_since_refill': 0.0,
        'capacity_estimates': [],
        'low_notified': False,
    }


def load_state():
    try:
        with open(HOPPER_FILE) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = _default_state()
    for key, value in _default_state().items():
        state.setdefault(key, value)
    return state


def save_state(state):
    with open(HOPPER_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def capacity_cups(state):
    """Median of recent refill-derived estimates; None while learning."""
    estimates = state['capacity_estimates']
    return round(median(estimates), 2) if estimates else None


def record_dispense(cups):
    state = load_state()
    state['cups_since_refill'] = round(state['cups_since_refill'] + cups, 2)
    save_state(state)
    return state


def record_refill(remaining_pct):
    """Record a refill. remaining_pct: rough % still full beforehand (0-95)."""
    state = load_state()
    consumed_fraction = 1 - remaining_pct / 100
    if consumed_fraction > 0 and state['cups_since_refill'] > 0:
        estimate = state['cups_since_refill'] / consumed_fraction
        state['capacity_estimates'] = (
            state['capacity_estimates'] + [round(estimate, 2)])[-ESTIMATES_KEPT:]
    state['cups_since_refill'] = 0.0
    state['last_refill'] = date.today().isoformat()
    state['low_notified'] = False
    save_state(state)
    return state


def _level(state, cap):
    return max(0.0, 1 - state['cups_since_refill'] / cap)


def status(daily_avg_cups=None):
    """Snapshot for the dashboard card."""
    state = load_state()
    cap = capacity_cups(state)
    info = {
        'cups_since_refill': state['cups_since_refill'],
        'last_refill': state['last_refill'],
        'capacity': cap,
        'learning': cap is None,
        'level': None,
        'days_left': None,
    }
    if cap:
        level = _level(state, cap)
        info['level'] = round(level, 2)
        if daily_avg_cups:
            info['days_left'] = int(cap * level / daily_avg_cups)
    return info


def check_low(daily_avg_cups=None):
    """Return an alert message when running low — once per refill cycle."""
    state = load_state()
    cap = capacity_cups(state)
    if not cap or state['low_notified']:
        return None
    level = _level(state, cap)
    days_left = (cap * level / daily_avg_cups) if daily_avg_cups else None
    if level <= LOW_LEVEL or (days_left is not None and days_left <= LOW_DAYS):
        state['low_notified'] = True
        save_state(state)
        if days_left is not None:
            return f"Hopper low — about {level:.0%} left (~{int(days_left)} days of food)"
        return f"Hopper low — about {level:.0%} left"
    return None
