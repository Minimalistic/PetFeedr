"""Feeding-log parsing and consumption statistics.

Pure stdlib — no Flask imports — so everything here is unit-testable.
Parse functions accept an optional `lines` argument for tests; by
default they read the live log files.
"""

import glob
import re
from datetime import datetime, timedelta

# Cups per portion size — single source of truth (was duplicated 3x)
PORTION_CUPS = {'small': 0.25, 'medium': 0.50, 'large': 0.75}

# Log line patterns, module-level so tests can exercise them directly.
# Manual feeding:    "2026-04-15 07:15:07 - Manual feeding triggered (small portion)"
# Scheduled feeding: "2026-04-15 07:15:07 - Feeding at 07:15 AM (small portion)"
# Completed (Python logging format):
#   "2026-04-29 06:00:00,908 - INFO - Feeding completed in 0.31s (small portion)"
# Groups: (date, time, portion)
MANUAL_PAT = re.compile(r'^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) - Manual feeding triggered \((\w+) portion\)')
SCHED_PAT = re.compile(r'^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) - Feeding at .* \((\w+) portion\)')
COMPLETED_PAT = re.compile(r'^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}),\d+ - INFO - Feeding completed in [\d.]+s \((\w+) portion\)')


def read_all_log_lines():
    """Read lines from feeding_log.txt and all rotated copies (feeding_log.txt.YYYY-MM-DD)."""
    lines = []
    # rotated files are older, sort them so oldest come first
    rotated = sorted(glob.glob('feeding_log.txt.*'))
    for path in rotated:
        try:
            with open(path, 'r') as f:
                lines.extend(f.readlines())
        except (FileNotFoundError, OSError):
            continue
    # current log file has the newest entries
    try:
        with open('feeding_log.txt', 'r') as f:
            lines.extend(f.readlines())
    except FileNotFoundError:
        pass
    return lines


def parse_recent_activity(days=14, limit=50, lines=None):
    """Parse feeding log to extract recent activity in a user-friendly format."""
    if lines is None:
        lines = read_all_log_lines()
    if not lines:
        return []

    activity = []
    cutoff_date = datetime.now() - timedelta(days=days)

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue

        match = MANUAL_PAT.match(line)
        feed_type = 'manual'
        if not match:
            match = SCHED_PAT.match(line) or COMPLETED_PAT.match(line)
            feed_type = 'scheduled'
        if not match:
            continue

        date_str, time_str, portion = match.groups()
        try:
            timestamp = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if timestamp < cutoff_date:
            break

        activity.append({
            'date': format_activity_date(timestamp),
            'time': timestamp.strftime("%I:%M %p"),
            'portion': portion,
            'type': feed_type
        })
        if len(activity) >= limit:
            break

    return activity


def format_activity_date(dt):
    """Format a date for activity display (Today, Yesterday, or date)."""
    today = datetime.now().date()
    activity_date = dt.date()

    if activity_date == today:
        return "Today"
    elif activity_date == today - timedelta(days=1):
        return "Yesterday"
    elif activity_date >= today - timedelta(days=6):
        return dt.strftime("%A")  # Day name
    else:
        return dt.strftime("%b %d")  # "Jan 05"


def parse_weekly_stats(lines=None):
    """Aggregate feeding data for the last 7 days by portion size."""
    if lines is None:
        lines = read_all_log_lines()
    if not lines:
        return []

    today = datetime.now().date()
    stats = {}
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        stats[d.isoformat()] = {
            'date': d.isoformat(),
            'day_label': d.strftime('%a'),
            'is_today': d == today,
            'small': 0, 'medium': 0, 'large': 0,
            'total_cups': 0.0,
            'manual_count': 0,
            'total_feedings': 0
        }

    for line in lines:
        stripped = line.strip()
        manual_match = MANUAL_PAT.match(stripped)
        sched_match = SCHED_PAT.match(stripped) or COMPLETED_PAT.match(stripped)
        match = manual_match or sched_match
        if match:
            date_str, _, portion = match.groups()
            if date_str in stats and portion in PORTION_CUPS:
                stats[date_str][portion] += 1
                stats[date_str]['total_cups'] += PORTION_CUPS[portion]
                stats[date_str]['total_feedings'] += 1
                if manual_match:
                    stats[date_str]['manual_count'] += 1

    return list(stats.values())


def build_week_summary(weekly_stats):
    """Build a one-line summary of the week's feeding activity."""
    total_manual = sum(d['manual_count'] for d in weekly_stats)
    total_feedings = sum(d['total_feedings'] for d in weekly_stats)
    if total_feedings == 0:
        return None
    if total_manual == 0:
        return "All feedings on schedule"
    manual_label = "1 manual feed" if total_manual == 1 else f"{total_manual} manual feeds"
    return f"{manual_label} this week"


def calculate_consumption_rate(weekly_stats):
    """Calculate consumption rate from weekly data."""
    total_cups = sum(d['total_cups'] for d in weekly_stats)
    days_with_data = sum(1 for d in weekly_stats if d['total_feedings'] > 0)
    if days_with_data == 0:
        return None
    daily_avg = total_cups / days_with_data
    weekly_avg = daily_avg * 7
    monthly_avg = daily_avg * 30
    lbs_per_cup = 0.25  # ~4 oz dry kibble per cup, 16 oz per lb
    return {
        'daily_cups': round(daily_avg, 2),
        'daily_lbs': round(daily_avg * lbs_per_cup, 2),
        'weekly_cups': round(weekly_avg, 1),
        'weekly_lbs': round(weekly_avg * lbs_per_cup, 1),
        'monthly_cups': round(monthly_avg, 1),
        'monthly_lbs': round(monthly_avg * lbs_per_cup, 1),
    }


def calculate_daily_total(schedules):
    """Calculate total cups per day from scheduled feedings."""
    total_cups = 0
    for sched in schedules:
        if isinstance(sched, dict):
            total_cups += PORTION_CUPS.get(sched.get('portion', 'small'), 0.25)
    return total_cups


def day_feedings(date_str, lines=None):
    """Return (feedings, total_cups) for a specific date (YYYY-MM-DD)."""
    if lines is None:
        lines = read_all_log_lines()

    feedings = []
    for line in lines:
        stripped = line.strip()
        manual_match = MANUAL_PAT.match(stripped)
        completed_match = COMPLETED_PAT.match(stripped)
        match = manual_match or completed_match
        if match:
            d, t, portion = match.groups()
            if d == date_str and portion in PORTION_CUPS:
                h, m, s = t.split(':')
                hour = int(h)
                time_12h = f"{hour % 12 or 12}:{m} {'AM' if hour < 12 else 'PM'}"
                feedings.append({
                    'time': time_12h,
                    'portion': portion,
                    'cups': PORTION_CUPS[portion],
                    'type': 'manual' if manual_match else 'scheduled'
                })

    total_cups = sum(f['cups'] for f in feedings)
    return feedings, total_cups
