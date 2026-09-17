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
import events

log = logging.getLogger('petfeedr')

HOPPER_FILE = 'hopper.json'
ESTIMATES_KEPT = 5
MIN_LEARN_CUPS = 2.0  # skip learning from refills after trivial consumption — tiny counters yield garbage capacity estimates
LOW_DAYS = 2       # alert when predicted days of food left drops to this
LOW_LEVEL = 0.15   # ...or when estimated fill level drops below this


def _default_state():
    # A fresh file assumes the hopper was just filled — true at first deploy
    return {
        'last_refill': date.today().isoformat(),
        'cups_since_refill': 0.0,
        'capacity_estimates': [],
        'cups_per_lb_estimates': [],
        'capacity_lbs_estimates': [],
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


def cups_per_lb(state):
    """Median nominal cups dispensed per lb of food; None until a weighed refill."""
    estimates = state['cups_per_lb_estimates']
    return round(median(estimates), 2) if estimates else None


def capacity_lbs(state):
    """Median weight the hopper holds when full; None until a weighed refill."""
    estimates = state['capacity_lbs_estimates']
    return round(median(estimates), 1) if estimates else None


def record_dispense(cups):
    state = load_state()
    state['cups_since_refill'] = round(state['cups_since_refill'] + cups, 2)
    save_state(state)
    return state


def record_refill(remaining_pct, lbs_added=None):
    """Record a refill. remaining_pct: rough % still full beforehand (0-95).
    lbs_added: optional weight of food poured in.

    Always resets the counter; only learns when at least MIN_LEARN_CUPS
    were dispensed since the last refill (a double top-up or accidental
    log would otherwise poison the estimates).

    Refills go to full, so the weight added equals the weight eaten since
    the last refill — cups_before / lbs_added is a cups-per-lb estimate
    that doesn't depend on the eyeballed remaining_pct at all. Capacity in
    lb comes straight from the weight too (lbs_added / fraction refilled)
    rather than via cups, so a noisy cups estimate can't skew it.
    """
    state = load_state()
    consumed_fraction = 1 - remaining_pct / 100
    cups_before = state['cups_since_refill']
    estimate = None
    per_lb_estimate = None
    if consumed_fraction > 0 and cups_before >= MIN_LEARN_CUPS:
        estimate = round(cups_before / consumed_fraction, 2)
        state['capacity_estimates'] = (
            state['capacity_estimates'] + [estimate])[-ESTIMATES_KEPT:]
    lbs_estimate = None
    if lbs_added and cups_before >= MIN_LEARN_CUPS:
        per_lb_estimate = round(cups_before / lbs_added, 2)
        state['cups_per_lb_estimates'] = (
            state['cups_per_lb_estimates'] + [per_lb_estimate])[-ESTIMATES_KEPT:]
        if consumed_fraction > 0:
            lbs_estimate = round(lbs_added / consumed_fraction, 2)
            state['capacity_lbs_estimates'] = (
                state['capacity_lbs_estimates'] + [lbs_estimate])[-ESTIMATES_KEPT:]
    state['cups_since_refill'] = 0.0
    state['last_refill'] = date.today().isoformat()
    state['low_notified'] = False
    save_state(state)
    events.record('refill', remaining_pct=remaining_pct, cups_before=cups_before,
                  capacity_estimate=estimate, capacity=capacity_cups(state),
                  lbs_added=lbs_added, cups_per_lb_estimate=per_lb_estimate,
                  capacity_lbs_estimate=lbs_estimate)
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
        'cups_per_lb': cups_per_lb(state),
        'capacity_lbs': capacity_lbs(state),
        'learning': cap is None,
        'level': None,
        'lbs_left': None,
        'days_left': None,
    }
    if cap:
        level = _level(state, cap)
        info['level'] = round(level, 2)
        if info['capacity_lbs']:
            info['lbs_left'] = round(info['capacity_lbs'] * level, 1)
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
        events.record('hopper_low', level=round(level, 2),
                      days_left=int(days_left) if days_left is not None else None)
        if days_left is not None:
            return f"Hopper low — about {level:.0%} left (~{int(days_left)} days of food)"
        return f"Hopper low — about {level:.0%} left"
    return None
