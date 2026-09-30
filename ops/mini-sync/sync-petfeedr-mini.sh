#!/usr/bin/env bash
# Runs on the Mac mini as jason (launchd: city.marsh.petfeedr-sync, every 15 min).
# Pulls the feeder's event journal, state files, and log archives off the
# Pi into a durable local store, renders the Obsidian note, then runs the
# watchdog. The Pi keeps only 14 days of logs; nothing is ever deleted from
# the store, so the full history lives here. One-way: nothing flows back.
set -uo pipefail  # no -e: a failed pull must still reach the watchdog

PI_HOST="${PI_HOST:-jason@petfeedr}"
PI_PATH=/home/jason/PetFeedr
STORE="${PETFEEDR_STORE:-$HOME/.petfeedr-data}"
HERE="$(cd "$(dirname "$0")" && pwd)"
# Pushover creds for the watchdog — launchd doesn't see shell exports
ALERT_ENV="${PETFEEDR_ALERT_ENV:-$HOME/.config/petfeedr/pushover.env}"

mkdir -p "$STORE/logs"

pull() {
  set -e
  # scp, not rsync: the journal doesn't exist until the first event is written,
  # and openrsync (macOS) has no --ignore-missing-args to tolerate that.
  scp -q -o ConnectTimeout=15 "$PI_HOST:$PI_PATH/hopper.json" "$STORE/hopper.json"
  # The schedule is the one piece of config not in git — kept here for SD-card restores
  scp -q -o ConnectTimeout=15 "$PI_HOST:$PI_PATH/feeding_schedules.txt" "$STORE/feeding_schedules.txt"
  scp -q -o ConnectTimeout=15 "$PI_HOST:$PI_PATH/todays_schedule.json" "$STORE/todays_schedule.json"
  scp -q -o ConnectTimeout=15 "$PI_HOST:$PI_PATH/feeding_events.jsonl" "$STORE/feeding_events.jsonl" \
    || echo "no event journal on the Pi yet"
  # No --delete: rotated logs accumulate here after the Pi ages them out.
  rsync -az --timeout=30 "$PI_HOST:$PI_PATH/feeding_log.txt*" "$STORE/logs/"
}

if (pull); then
  date +%s > "$STORE/last_contact"
  # The watchdog needs 15-min freshness; the vault note doesn't — rendering
  # hourly keeps iCloud from syncing a new "updated:" stamp four times an hour
  last_render=$(cat "$STORE/last_render" 2>/dev/null || echo 0)
  if [ $(( $(date +%s) - last_render )) -ge 3300 ]; then
    python3 "$HERE/render_note.py" "$STORE" && date +%s > "$STORE/last_render"
  fi
else
  echo "$(date '+%F %T') pull from $PI_HOST failed"
fi

if [ -f "$ALERT_ENV" ]; then
  set -a; . "$ALERT_ENV"; set +a
fi
python3 "$HERE/watchdog.py" "$STORE"
