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
PetFeedr.py              # Entry point: schedule loop + daily regeneration
web_interface.py          # Flask app: all routes + log parsing
servo_controller.py       # Motor control: portion sizes, dispense cycles, anti-jam agitation
DRV8825.py                # GPIO abstraction; auto-falls back to mock_gpio.py in sim mode
mock_gpio.py              # Simulation stub for RPi.GPIO
feeding_schedules.txt     # Persistent schedule store: "HH:MM,portion[,fixed]"
feeding_log.txt           # Rotating log (14-day retention)
todays_schedule.json      # Today's randomized schedule, regenerated daily
deploy.sh                 # rsync-based deploy to Pi with SSH multiplexing
setup-pi.sh               # One-time Pi setup (venv, systemd unit)
```

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
