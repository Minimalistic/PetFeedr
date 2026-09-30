"""View-model for the index page: schedule rows, timeline, stats, hopper card.

Split out of web_interface so the routes file holds routes. Read-only —
nothing here mutates state.
"""

from datetime import datetime

from feeder_core import load_todays_schedule, log
from feeding_stats import (parse_recent_activity, parse_weekly_stats, build_week_summary,
                           calculate_consumption_rate, calculate_daily_total)
from servo_controller import PORTION_SIZES
import hopper
import schedule_store


def read_schedules_with_details():
    """Schedule entries merged with today's actual (possibly randomized) times."""
    todays_by_base = {s['base_time']: s for s in load_todays_schedule() or []}

    schedules = []
    for entry in schedule_store.read_entries():
        time_str = entry['time']
        actual_time = todays_by_base.get(time_str, {}).get('actual_time', time_str)
        try:
            base_dt = datetime.strptime(time_str, "%H:%M")
            actual_dt = datetime.strptime(actual_time, "%H:%M")
        except ValueError:
            log.error(f"Error parsing time: {time_str}")
            continue
        schedules.append({
            'base_time_24h': time_str,
            'base_time_12h': base_dt.strftime("%I:%M %p"),
            'actual_time_24h': actual_time,
            'actual_time_12h': actual_dt.strftime("%I:%M %p"),
            'portion': entry['portion'],
            'is_fixed': entry['is_fixed'],
            'randomized': actual_time != time_str,
            'sort_key': actual_dt
        })

    schedules.sort(key=lambda x: x['sort_key'])
    return schedules


def get_next_feeding(schedules):
    """Get the next upcoming feeding from the schedule."""
    if not schedules:
        return None

    current_time = datetime.now().strftime("%H:%M")
    for sched in schedules:
        if sched['actual_time_24h'] > current_time:
            return sched

    # If no upcoming feeding today, return the first one (for tomorrow)
    return schedules[0]


def mark_past_feedings(schedules):
    """Mark which feedings are past and which is next."""
    current_time = datetime.now().strftime("%H:%M")
    found_next = False

    for sched in schedules:
        if sched['actual_time_24h'] < current_time:
            sched['is_past'] = True
            sched['is_next'] = False
        elif not found_next:
            sched['is_past'] = False
            sched['is_next'] = True
            found_next = True
        else:
            sched['is_past'] = False
            sched['is_next'] = False

    return schedules


def build_timeline(schedules):
    """Adds time_minutes to each schedule; returns (start, end, hour ticks)."""
    for s in schedules:
        h, m = s['actual_time_24h'].split(':')
        s['time_minutes'] = int(h) * 60 + int(m)

    if schedules:
        times_min = [s['time_minutes'] for s in schedules]
        timeline_start = max(0, min(times_min) - 60)
        timeline_end = min(1439, max(times_min) + 60)
    else:
        timeline_start, timeline_end = 360, 1320  # 6AM-10PM default

    timeline_hours = []
    first_hour = ((timeline_start // 60) + 1) * 60
    for mins in range(first_hour, timeline_end, 60):
        h = mins // 60
        pct = ((mins - timeline_start) / (timeline_end - timeline_start)) * 100
        show_label = (h % 2 == 0)
        label = f"{h % 12 or 12}{'AM' if h < 12 else 'PM'}" if show_label else None
        timeline_hours.append({'label': label, 'pct': pct})

    return timeline_start, timeline_end, timeline_hours


def hopper_card(consumption):
    status = hopper.status(consumption['daily_cups'] if consumption else None)
    try:
        status['last_refill_label'] = datetime.strptime(
            status['last_refill'], "%Y-%m-%d").strftime("%b %d")
    except (ValueError, TypeError):
        status['last_refill_label'] = status['last_refill']
    # Preselect the "what was left" guess nearest the app's own level estimate,
    # so the form confirms its guess instead of quizzing from scratch
    level = status.get('level')
    status['refill_default'] = (
        min([0, 10, 25, 50, 75], key=lambda c: abs(c - level * 100))
        if level is not None else 10)
    return status


def index_context():
    """Everything index.html renders, minus app-level constants."""
    schedules = mark_past_feedings(read_schedules_with_details())
    recent_activity = parse_recent_activity(days=1, limit=1)
    timeline_start, timeline_end, timeline_hours = build_timeline(schedules)

    weekly_stats = parse_weekly_stats()
    max_daily_cups = max(max((d['total_cups'] for d in weekly_stats), default=0.5), 0.5)
    consumption = calculate_consumption_rate(weekly_stats)

    return {
        'schedules': schedules,
        'next_feeding': get_next_feeding(schedules),
        'portion_info': {name: desc for name, (cycles, desc) in PORTION_SIZES.items()},
        'daily_total': calculate_daily_total(schedules),
        'all_fed_today': bool(schedules) and all(s.get('is_past') for s in schedules),
        'last_feeding': recent_activity[0] if recent_activity else None,
        'timeline_start': timeline_start,
        'timeline_end': timeline_end,
        'timeline_hours': timeline_hours,
        'weekly_stats': weekly_stats,
        'max_daily_cups': max_daily_cups,
        'week_summary': build_week_summary(weekly_stats),
        'consumption': consumption,
        'hopper': hopper_card(consumption),
    }
