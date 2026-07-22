# PetFeedr

Raspberry Pi-based automated pet feeder. Manages a stepper motor (DRV8825 driver)
to dispense food on a schedule. Features optional +/-30-minute randomization per
feeding to mimic natural patterns, manual trigger support, and a Flask web UI
served as a PWA.

No database — schedules and logs are flat files.

## Stack

- **Language**: Python 3
- **Web framework**: Flask
- **Scheduling**: `schedule` library (in-process)
- **Hardware**: DRV8825 stepper motor driver via `RPi.GPIO`
- **Simulation mode**: auto-enabled when `RPi.GPIO` is unavailable (dev on Mac)
- **Frontend**: Vanilla JS PWA — `static/main.js`, `static/sw.js`, `static/manifest.json`

## Key Files

```
PetFeedr.py              # Entry point: main schedule loop + Flask daemon thread (one process)
feeder_core.py            # Shared core: logging, STATE_LOCK, feed_pet, randomization, resync
web_interface.py          # Flask routes (also runs standalone as a UI-only dev server)
feeding_stats.py          # Log parsing + consumption stats (pure stdlib, unit-tested)
hopper.py                 # Hopper level tracking; learns capacity from refill feedback
notify.py                 # Pushover alerts (PUSHOVER_TOKEN/PUSHOVER_USER env; fail-soft)
servo_controller.py       # Motor control: portion sizes, dispense cycles, anti-jam agitation
DRV8825.py                # GPIO abstraction; auto-falls back to mock_gpio.py in sim mode
mock_gpio.py              # Simulation stub for RPi.GPIO
test_feeder.py            # unittest suite (python3 -m unittest)
feeding_schedules.txt     # Persistent schedule store: "HH:MM,portion[,fixed]"
feeding_log.txt           # Rotating log, midnight rotation, 14-day retention
todays_schedule.json      # Today's randomized schedule; source of truth for today's jobs
hopper.json               # Hopper counter + learned capacity estimates
deploy.sh                 # rsync-based deploy to Pi with SSH multiplexing
setup-pi.sh               # One-time Pi setup (venv, systemd unit w/ EnvironmentFile)
```

Key invariants:
- **One process.** The scheduler owns the main thread; Flask runs in a
  daemon thread. Never spawn web_interface separately in production —
  its `__main__` entry is a console-only dev server.
- **All schedule/motor/file mutations hold `feeder_core.STATE_LOCK`.**
  The `schedule` library is not thread-safe.
- **Web mutations call `resync_today()`** so edits take effect
  immediately; `todays_schedule.json` is the source of truth for
  today's jobs.
- **The "Feeding completed" log line is the single dispense record**
  (tagged `, manual` / `, scheduled`). Don't add other countable lines
  — the stats regexes in feeding_stats.py parse only this family.
- **Log through `logging.getLogger('petfeedr')`**, never the root
  logger (root goes to stderr/journald, not feeding_log.txt).

## Data Model (Flat Files)

**`feeding_schedules.txt`** — one entry per line: `HH:MM,portion[,fixed]`
- `portion`: `small` | `medium` | `large` (1/2/3 dispense cycles)
- `fixed`: optional; omit to enable randomization

**`todays_schedule.json`** — generated at startup, rebuilt on new day

**`feeding_log.txt`** — rotated daily, 14 copies retained

## Running

### Development (Mac — no hardware)
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 PetFeedr.py
```
Simulation mode activates automatically. Web UI at `http://localhost:5000`.

### On the Pi (production)
```bash
sudo systemctl start petfeedr.service
```

## Deployment

```bash
./deploy.sh
```
Backs up current Pi install, syncs files, updates deps, restarts service. Preserves schedule/log files.

Target: `pi@petfeedr.local` (override with `PI_HOST` env var).

Live: `http://petfeedr.local:5000` (local network only — no auth).

## GPIO Pin Mapping (DRV8825)

| Function  | GPIO Pin |
|-----------|----------|
| Direction | 13       |
| Step      | 19       |
| Enable    | 12       |
| Mode 1    | 16       |
| Mode 2    | 17       |
| Mode 3    | 20       |
