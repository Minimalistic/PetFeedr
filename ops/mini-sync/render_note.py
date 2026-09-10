#!/usr/bin/env python3
"""Render the PetFeedr Obsidian note from the mini's local store.

Usage: render_note.py <store-dir> [<note-path>]

Reads feeding_events.jsonl, hopper.json, and logs/feeding_log.txt* from the
store. Dispenses come from the journal where it exists and from the log
archives before it did (the two overlap at the journal's first day and are
deduplicated). Pure stdlib; imports the feeder's own log regexes so the
parsing can never drift from the device's.
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
from feeding_stats import COMPLETED_RE, FAILED_RE, PORTION_CUPS  # noqa: E402

DEFAULT_NOTE = os.path.expanduser(
    '~/Library/Mobile Documents/iCloud~md~obsidian/Documents/JasonWiki/Home/PetFeedr Feeding Log.md')
DEDUP_WINDOW = timedelta(seconds=3)  # journal write and log line land within the same feeding


# ---- loading ---------------------------------------------------------------

def load_events(path):
    events = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get('sim'):
                    continue  # dev-box runs never count as food
                events.append(ev)
    except FileNotFoundError:
        pass
    return events


def load_log_lines(logs_dir):
    lines = []
    try:
        names = sorted(os.listdir(logs_dir))
    except FileNotFoundError:
        return lines
    for name in names:
        if name.startswith('feeding_log.txt'):
            with open(os.path.join(logs_dir, name), errors='replace') as f:
                lines.extend(f.readlines())
    return lines


def dispenses_from_log(lines):
    out = []
    for line in lines:
        m = COMPLETED_RE.match(line.strip())
        if not m:
            continue
        ts = datetime.strptime(f"{m['date']} {m['time']}", "%Y-%m-%d %H:%M:%S")
        portion = m['portion']
        out.append({'ts': ts, 'portion': portion, 'cups': PORTION_CUPS.get(portion, 0.25),
                    'source': m['source'] or 'scheduled', 'origin': 'log'})
    return out


def failures_from_log(lines):
    out = []
    for line in lines:
        m = FAILED_RE.match(line.strip())
        if m:
            ts = datetime.strptime(f"{m['date']} {m['time']}", "%Y-%m-%d %H:%M:%S")
            out.append({'ts': ts, 'portion': m['portion'], 'source': m['source'], 'error': ''})
    return out


def merge_dispenses(events, log_lines):
    """Journal dispenses plus log dispenses not already covered by one."""
    merged = []
    for ev in events:
        if ev.get('event') != 'dispense':
            continue
        merged.append({'ts': datetime.fromisoformat(ev['ts']), 'portion': ev['portion'],
                       'cups': ev.get('cups', PORTION_CUPS.get(ev['portion'], 0.25)),
                       'source': ev.get('source', 'scheduled'), 'origin': 'journal'})
    for d in dispenses_from_log(log_lines):
        covered = any(j['portion'] == d['portion'] and abs(j['ts'] - d['ts']) <= DEDUP_WINDOW
                      for j in merged if j['origin'] == 'journal')
        if not covered:
            merged.append(d)
    merged.sort(key=lambda d: d['ts'])
    return merged


# ---- aggregation -----------------------------------------------------------

def daily_totals(dispenses):
    days = defaultdict(lambda: {'cups': 0.0, 'feedings': 0, 'manual': 0, 'times': []})
    for d in dispenses:
        day = days[d['ts'].date()]
        day['cups'] += d['cups']
        day['feedings'] += 1
        day['manual'] += d['source'] == 'manual'
        day['times'].append(d['ts'].strftime('%H:%M'))
    return dict(days)


def period_summary(days, since, until):
    rows = [v for k, v in days.items() if since <= k <= until]
    cups = sum(r['cups'] for r in rows)
    fed_days = sum(1 for r in rows if r['feedings'])
    return {'cups': cups, 'feedings': sum(r['feedings'] for r in rows),
            'manual': sum(r['manual'] for r in rows),
            'avg': cups / fed_days if fed_days else 0.0, 'days': fed_days}


def hopper_snapshot(hopper, daily_avg):
    caps = hopper.get('capacity_estimates') or []
    cap = sorted(caps)[len(caps) // 2] if caps else None  # median, matching hopper.py
    snap = {'cap': cap, 'since': hopper.get('cups_since_refill', 0.0),
            'last_refill': hopper.get('last_refill'), 'level': None, 'left': None, 'days': None}
    if cap:
        snap['level'] = max(0.0, 1 - snap['since'] / cap)
        snap['left'] = cap * snap['level']
        if daily_avg:
            snap['days'] = int(snap['left'] / daily_avg)
    return snap


# ---- rendering -------------------------------------------------------------

def fmt_cups(c):
    return f"{c:.2f}".rstrip('0').rstrip('.')


def render(dispenses, events, hopper, log_failures=(), now=None):
    now = now or datetime.now()
    today = now.date()
    days = daily_totals(dispenses)
    week = period_summary(days, today - timedelta(days=6), today)
    month = period_summary(days, today - timedelta(days=29), today)
    snap = hopper_snapshot(hopper, week['avg'])
    refills = [e for e in events if e.get('event') == 'refill']
    lows = [e for e in events if e.get('event') == 'hopper_low']
    failures = [e for e in events if e.get('event') == 'failure']

    out = []
    out.append('---')
    out.append('type: feeder-log')
    out.append(f"updated: {now.strftime('%Y-%m-%dT%H:%M')}")
    out.append('tags: [petfeedr, pets, home]')
    out.append('---')
    out.append('# PetFeedr Feeding Log')
    out.append('')
    out.append('Auto-generated hourly from the feeder on the Pi by '
               '`PetFeedr/ops/mini-sync`. Edits here are overwritten.')
    out.append('')
    out.append('## Now')
    if snap['cap']:
        line = (f"- **Hopper:** ~{snap['level']:.0%} full, about {fmt_cups(snap['left'])} cups left"
                f" (capacity ≈{fmt_cups(snap['cap'])} cups)")
        if snap['days'] is not None:
            line += f", roughly {snap['days']} days at the current rate"
        out.append(line)
    else:
        out.append(f"- **Hopper:** learning capacity; {fmt_cups(snap['since'])} cups dispensed since last refill")
    out.append(f"- **Last refill logged:** {snap['last_refill'] or 'never'}")
    if dispenses:
        last = dispenses[-1]
        out.append(f"- **Last feeding:** {last['ts'].strftime('%Y-%m-%d %H:%M')} — "
                   f"{last['portion']} ({last['source']})")
    else:
        out.append('- **Last feeding:** no records yet')
    t = days.get(today)
    out.append(f"- **Today:** {fmt_cups(t['cups']) if t else '0'} cups in {t['feedings'] if t else 0} feedings")
    out.append('')
    out.append('## Consumption')
    out.append('')
    out.append('| Period | Cups | Feedings | Manual | Avg cups/day |')
    out.append('|---|---|---|---|---|')
    for label, p in (('Last 7 days', week), ('Last 30 days', month)):
        out.append(f"| {label} | {fmt_cups(p['cups'])} | {p['feedings']} | {p['manual']} | {fmt_cups(p['avg'])} |")
    out.append('')
    out.append('## Daily (last 14 days)')
    out.append('')
    out.append('| Date | Cups | Feedings | Manual | Times |')
    out.append('|---|---|---|---|---|')
    for i in range(14):
        d = today - timedelta(days=i)
        r = days.get(d)
        if r:
            out.append(f"| {d} | {fmt_cups(r['cups'])} | {r['feedings']} | {r['manual']} | {', '.join(r['times'])} |")
        else:
            out.append(f"| {d} | 0 | 0 | 0 | |")
    out.append('')
    out.append('## Refills')
    out.append('')
    if refills:
        out.append('| Date | Was ~% full | Cups since previous | Capacity estimate |')
        out.append('|---|---|---|---|')
        for r in reversed(refills):
            est = fmt_cups(r['capacity_estimate']) if r.get('capacity_estimate') else 'not learned'
            out.append(f"| {r['ts'][:16].replace('T', ' ')} | {r['remaining_pct']:.0f}% | "
                       f"{fmt_cups(r['cups_before'])} | {est} |")
    else:
        out.append('None in the journal yet (refills before 2026-09-10 predate it).')
    out.append('')
    out.append('## Failures and alerts')
    out.append('')
    # Journal failures carry the error text; log-only failures (pre-journal) just the fact
    all_failures = [(datetime.fromisoformat(f['ts']), f['portion'], f['source'], f.get('error', ''))
                    for f in failures]
    journal_times = {t for t, *_ in all_failures}
    all_failures += [(f['ts'], f['portion'], f['source'], '') for f in log_failures
                     if not any(abs(f['ts'] - t) <= DEDUP_WINDOW for t in journal_times)]
    if not all_failures and not lows:
        out.append('None recorded.')
    for ts, portion, source, error in sorted(all_failures, reverse=True):
        out.append(f"- {ts.strftime('%Y-%m-%d %H:%M')} — feeding FAILED ({portion}, {source}){': ' + error if error else ''}")
    for l in reversed(lows):
        out.append(f"- {l['ts'][:16].replace('T', ' ')} — hopper low ({l['level']:.0%}, ~{l['days_left']} days)")
    out.append('')
    out.append('## History')
    out.append('')
    if dispenses:
        first = dispenses[0]['ts'].date()
        out.append(f"Records since {first}: {len(dispenses)} feedings, "
                   f"{fmt_cups(sum(d['cups'] for d in dispenses))} cups total.")
        out.append('')
        # "Days logged" exposes partial coverage: pre-journal months come from
        # deploy-backup snapshots of a 14-day rotating log, so they have holes.
        months = defaultdict(lambda: {'cups': 0.0, 'feedings': 0, 'manual': 0, 'days': set()})
        for d in dispenses:
            m = months[d['ts'].strftime('%Y-%m')]
            m['cups'] += d['cups']
            m['feedings'] += 1
            m['manual'] += d['source'] == 'manual'
            m['days'].add(d['ts'].date())
        out.append('| Month | Cups | Feedings | Manual | Days logged |')
        out.append('|---|---|---|---|---|')
        for k in sorted(months, reverse=True):
            m = months[k]
            out.append(f"| {k} | {fmt_cups(m['cups'])} | {m['feedings']} | {m['manual']} | {len(m['days'])} |")
    else:
        out.append('No feedings recorded yet.')
    out.append('')
    return '\n'.join(out)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    store = sys.argv[1]
    note_path = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_NOTE
    events = load_events(os.path.join(store, 'feeding_events.jsonl'))
    log_lines = load_log_lines(os.path.join(store, 'logs'))
    try:
        with open(os.path.join(store, 'hopper.json')) as f:
            hopper = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        hopper = {}
    dispenses = merge_dispenses(events, log_lines)
    text = render(dispenses, events, hopper, failures_from_log(log_lines))
    os.makedirs(os.path.dirname(note_path), exist_ok=True)
    tmp = note_path + '.tmp'
    with open(tmp, 'w') as f:  # write-then-rename so iCloud never syncs a half-written note
        f.write(text)
    os.replace(tmp, note_path)
    print(f"rendered {len(dispenses)} feedings → {note_path}")


if __name__ == '__main__':
    main()
