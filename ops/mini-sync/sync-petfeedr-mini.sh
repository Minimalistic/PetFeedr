#!/usr/bin/env bash
# Runs on the Mac mini as jason (launchd: city.marsh.petfeedr-sync, hourly).
# Pulls the feeder's event journal, hopper state, and log archives off the
# Pi into a durable local store, then renders the Obsidian note. The Pi
# keeps only 14 days of logs; nothing is ever deleted from the store, so
# the full history lives here. One-way: nothing flows back to the Pi.
set -euo pipefail

PI_HOST="${PI_HOST:-jason@petfeedr}"
PI_PATH=/home/jason/PetFeedr
STORE="${PETFEEDR_STORE:-$HOME/.petfeedr-data}"
HERE="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$STORE/logs"

# scp, not rsync: the journal doesn't exist until the first event is written,
# and openrsync (macOS) has no --ignore-missing-args to tolerate that.
scp -q -o ConnectTimeout=15 "$PI_HOST:$PI_PATH/hopper.json" "$STORE/hopper.json"
scp -q -o ConnectTimeout=15 "$PI_HOST:$PI_PATH/feeding_events.jsonl" "$STORE/feeding_events.jsonl" \
  || echo "no event journal on the Pi yet"

# No --delete: rotated logs accumulate here after the Pi ages them out.
rsync -az --timeout=30 "$PI_HOST:$PI_PATH/feeding_log.txt*" "$STORE/logs/"

python3 "$HERE/render_note.py" "$STORE"
