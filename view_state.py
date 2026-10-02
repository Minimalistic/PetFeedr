"""Display-ready dashboard state, served as JSON to the client-side renderer.

dashboard.index_context() gathers the data; this module turns it into the
exact strings and numbers each card shows, so the browser only places them.
One formatter for "1¼ cups" or "4:00 AM" means the UI can't drift between
a server-rendered and a client-rendered spelling.

Read-only, like dashboard.py.
"""

import hashlib
from pathlib import Path

from DRV8825 import SIMULATION_MODE
from feeding_stats import PORTION_CUPS
from servo_controller import PORTION_SIZES, DEFAULT_PORTION
import dashboard

APP_VERSION = "1.5.0"
STATIC_DIR = Path(__file__).parent / 'static'


def cups(value):
    """0.75 → "¾ cup", 1.25 → "1¼ cups" — kitchen fractions read faster than decimals."""
    quarters = int(round(float(value) * 4))
    whole, frac = divmod(quarters, 4)
    text = (str(whole) if whole else '') + ['', '¼', '½', '¾'][frac] or '0'
    return f"{text} cup{'' if quarters <= 4 and quarters != 0 else 's'}"


def compute_asset_version():
    """Short hash of the shipped front-end files. Embedded in the page and in
    every state payload: a long-lived tab that sees a different value knows a
    deploy happened and reloads itself once to pick up the new code."""
    digest = hashlib.sha256()
    for path in sorted(STATIC_DIR.rglob('*')):
        if path.is_file() and path.suffix in ('.js', '.css', '.json', '.svg'):
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


ASSET_VERSION = compute_asset_version()

_STATUS_TEXT = {
    'fed': 'Fed',
    'failed': 'Failed — check for a jam',
    'missed': 'Missed',
    'due': 'Due now',
}


def _status_text(slot):
    if slot['status'] == 'late':
        mins = f"{slot['late_min']} min " if slot.get('late_min') else ''
        return f"Caught up {mins}late"
    if slot['status'] == 'upcoming':
        return 'Next' if slot.get('is_next') else 'Upcoming'
    return _STATUS_TEXT[slot['status']]


def _status_badge(slot):
    if slot['status'] == 'late':
        return f"+{slot['late_min']}m" if slot.get('late_min') else '+late'
    return {'missed': '!', 'failed': '✕'}.get(slot['status'])


def _next_card(ctx):
    nxt = ctx['next_feeding']
    if not nxt:
        return None
    return {
        'time': nxt['actual_time_12h'],
        'time24': nxt['actual_time_24h'],
        'portion': nxt['portion'],
        'randomized': nxt['randomized'],
        'all_fed': ctx['all_fed_today'],
    }


def _timeline(ctx):
    start, end = ctx['timeline_start'], ctx['timeline_end']
    span = end - start
    slots = []
    for s in ctx['schedules']:
        slots.append({
            'key': s['base_time_24h'],
            'time': s['actual_time_12h'],
            'pct': round((s['time_minutes'] - start) / span * 100, 3) if span > 0 else 50,
            'portion': s['portion'],
            'is_fixed': s['is_fixed'],
            'is_past': s.get('is_past', False),
            'is_next': s.get('is_next', False),
            'status': s['status'],
            'status_text': _status_text(s),
            'badge': _status_badge(s),
        })
    return {'start': start, 'end': end, 'hours': ctx['timeline_hours'], 'slots': slots}


def _schedule_rows(ctx):
    """The editor lists the times as set, not today's randomized draw."""
    rows = sorted(ctx['schedules'], key=lambda s: s['base_time_24h'])
    return [{'base_time': s['base_time_24h'], 'time': s['base_time_12h'],
             'portion': s['portion'], 'is_fixed': s['is_fixed']} for s in rows]


def _feed_card(ctx):
    manual = ctx['manual']
    no_extras = not manual['fits']['small']
    return {
        'fits': manual['fits'],
        'no_extras': no_extras,
        'extras_label': 'No extras left today' if no_extras
                        else f"{cups(manual['remaining'])} of extras left today",
        'allowance_title': f"Manual feeds are capped at {cups(manual['allowance'])} a day",
    }


def _stats_card(ctx):
    rhythm = ctx['rhythm']
    days = []
    for day in rhythm['days']:
        fed = [m for m in day['marks'] if m['kind'] in ('fed', 'manual', 'late')]
        notes = ''.join(f"; {m['label']}" for m in day['marks'] if m['kind'] not in ('fed', 'upcoming'))
        days.append({
            'date': day['date'],
            'day_label': day['day_label'],
            'is_today': day['is_today'],
            'cups_short': cups(day['total_cups']).split(' ')[0],
            'aria': f"{day['day_label']}, {cups(day['total_cups'])}, {len(fed)} feedings{notes}",
            'marks': day['marks'],
        })

    on_time = ctx['on_time']
    if on_time['streak_days'] >= 2:
        streak = {'hot': True, 'text': f"{on_time['streak_days']}-day on-time streak",
                  'title': f"{on_time['week_on_time']} of {on_time['week_total']} scheduled feeds on time this week"}
    elif on_time['week_total']:
        streak = {'hot': False, 'text': f"{on_time['week_on_time']}/{on_time['week_total']} on time", 'title': ''}
    else:
        streak = None

    consumption = ctx['consumption']
    return {
        'has_data': any(d['marks'] for d in rhythm['days']),
        'days': days,
        'guides': rhythm['guides'],
        'streak': streak,
        'week_summary': ctx['week_summary'],
        'consumption_label': (f"≈ {cups(consumption['daily_cups'])}/day · {consumption['monthly_lbs']:g} lbs/mo"
                              if consumption else None),
    }


def _hopper_card(ctx):
    h = ctx['hopper']
    card = {'learning': h['learning'], 'refill_default': h['refill_default']}
    if h['learning']:
        n = h['cups_since_refill']
        card['learning_amount'] = f"{n} cup{'s' if n != 1 else ''}"
        card['last_refill_label'] = h['last_refill_label']
        return card

    pct = int(round(h['level'] * 100))
    capacity = f"~{h['capacity']} cups"
    if h['capacity_lbs']:
        capacity = f"~{h['capacity_lbs']:g} lb ({int(round(h['capacity_lbs'] * 16))} oz), " + capacity
    card.update({
        'level': h['level'],
        'pct': pct,
        'low': h['level'] <= 0.15,
        'headline': f"~{pct}% full",
        'lbs_label': f"· ~{h['lbs_left']:g} lb" if h['lbs_left'] is not None else None,
        'refill_by': f"Refill by {h['refill_by_label']}" if h.get('refill_by_label') else None,
        'refill_urgent': h.get('refill_by_label') == 'today',
        'days_label': (f"~{h['days_left']} day{'s' if h['days_left'] != 1 else ''} of food · "
                       f"empty around {h['empty_label']}") if h.get('refill_by_label') else None,
        'capacity_label': f"Holds {capacity}",
    })
    return card


def build():
    """Everything the dashboard shows, as JSON-safe display values."""
    ctx = dashboard.index_context()
    last = ctx['last_feeding']
    return {
        'asset_version': ASSET_VERSION,
        'app': {'version': APP_VERSION, 'simulation': SIMULATION_MODE},
        'portions': [{'name': name, 'letter': name[0].upper(), 'label': name.capitalize(),
                      'desc': desc, 'cups': PORTION_CUPS[name]}
                     for name, (cycles, desc) in PORTION_SIZES.items()],
        'default_portion': DEFAULT_PORTION,
        'next': _next_card(ctx),
        'timeline': _timeline(ctx),
        'daily_total_label': cups(ctx['daily_total']),
        'schedule': _schedule_rows(ctx),
        'feed': _feed_card(ctx),
        'stats': _stats_card(ctx),
        'hopper': _hopper_card(ctx),
        'last_fed': f"{last['date']} at {last['time']}" if last else None,
    }
