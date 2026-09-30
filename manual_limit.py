"""Daily cap on manual feeds — shared by the /feed route and the dashboard.

Manual feeds are capped per day so a double-tap, a kid with the phone, or a
stray request can't empty the hopper into the bowl. The allowance is half the
scheduled daily total, with a floor so a light (or empty) schedule still
leaves room for a real top-up. Resets at midnight.
"""

from datetime import date

from feeding_stats import PORTION_CUPS, day_feedings
import schedule_store

CAP_FRACTION = 0.5
CAP_FLOOR_CUPS = 0.75
COOLDOWN_S = 60


def allowance_cups():
    scheduled = sum(PORTION_CUPS[e['portion']] for e in schedule_store.read_entries())
    return max(CAP_FLOOR_CUPS, scheduled * CAP_FRACTION)


def used_today_cups():
    feedings, _ = day_feedings(date.today().isoformat())
    return sum(f['cups'] for f in feedings if f['type'] == 'manual')


def status():
    """Snapshot for the feed card: what's left and which portions still fit."""
    allowance = allowance_cups()
    used = used_today_cups()
    remaining = max(0.0, allowance - used)
    return {
        'allowance': allowance,
        'used': used,
        'remaining': remaining,
        'fits': {name: cups <= remaining + 1e-9 for name, cups in PORTION_CUPS.items()},
    }
