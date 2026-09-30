# Restore the Pi from a dead SD card

About 45 minutes, mostly waiting on flashing and apt. Nothing on the card
is irreplaceable: code is in git, and data plus config are on the mini.

| What | Where the good copy lives |
|---|---|
| Code, systemd unit, timezone | this repo (`deploy.sh`, `setup-pi.sh`) |
| `feeding_schedules.txt`, `hopper.json`, `feeding_events.jsonl` | `~/.petfeedr-data/` on the mini (pulled every 15 min) |
| `.env` (Pushover creds) | newest `~/PetFeedr-backups/*/.env` (every deploy snapshots it) |
| Rotated logs | `~/.petfeedr-data/logs/` (history only; the Pi doesn't need them back) |

**Not covered: Pi-hole and Samba also run on this Pi.** If the network's
DNS points at it, name resolution for the house goes down with the card.
Their config isn't backed up anywhere in this repo.

## Precondition

- A spare SD card, 8 GB or larger.
- The mini's store is current: `ls -l ~/.petfeedr-data/feeding_schedules.txt`.
- Feed by hand until step 7. The watchdog will already have paged "unreachable".

## Steps

1. **Flash.** Raspberry Pi Imager → Raspberry Pi OS Lite. In OS customisation, set:
   hostname `petfeedr`, user `jason`, SSH public-key only (`~/.ssh/id_ed25519.pub`),
   Wi-Fi, and timezone `America/Chicago`.
2. **Boot and clear old host keys** (on the mini):
   ```bash
   ssh-keygen -R petfeedr; ssh-keygen -R petfeedr.local
   ssh jason@petfeedr.local 'echo ok'
   ```
3. **Tailscale.** In the admin console, delete the old `petfeedr` machine
   *first*. Otherwise the new node registers as `petfeedr-1`, and deploy.sh
   and the sync break.
   ```bash
   ssh jason@petfeedr.local 'curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up'
   ```
   Open the auth URL it prints, then check that `ssh jason@petfeedr 'echo ok'` works.
4. **Build prerequisites.** RPi.GPIO compiles from source on current Python:
   ```bash
   ssh jason@petfeedr 'sudo apt update && sudo apt install -y python3-venv python3-dev gcc rsync'
   ```
5. **Deploy the code** from the repo on the mini:
   ```bash
   ./deploy.sh
   ```
   Expected on a fresh card: "No existing installation to backup", then the
   final `systemctl start` fails because the unit doesn't exist yet. Step 7
   installs it.
6. **Restore state** before anything starts feeding:
   ```bash
   cd ~/.petfeedr-data
   scp feeding_schedules.txt hopper.json feeding_events.jsonl jason@petfeedr:PetFeedr/
   scp "$(ls -td ~/PetFeedr-backups/*/ | head -1).env" jason@petfeedr:PetFeedr/.env
   ssh jason@petfeedr 'chmod 600 ~/PetFeedr/.env'
   ```
7. **Install and start the service** (sets the timezone again, writes the unit, starts it):
   ```bash
   ssh jason@petfeedr 'cd ~/PetFeedr && ./setup-pi.sh'
   ```

## Postcondition

```bash
ssh jason@petfeedr 'systemctl is-active petfeedr; cat ~/PetFeedr/feeding_schedules.txt; grep -c "\[SIM\]" ~/PetFeedr/feeding_log.txt'
launchctl kickstart gui/501/city.marsh.petfeedr-sync && sleep 20 && tail -3 ~/Library/Logs/petfeedr-sync.log
```

- `active`, the schedule matches `~/.petfeedr-data/feeding_schedules.txt`, and the `[SIM]` count is **0**.
  On a Pi, a GPIO import failure crashes the service rather than simulating,
  so `activating`/restart-looping means step 4 or the pip install failed:
  `journalctl -u petfeedr -n 30`.
- The dashboard loads at `http://petfeedr:5000` and the hopper card shows the restored level.
- Do one manual **small** feed from the dashboard and watch kibble come out. That
  proves the motor, not just the software.
- The watchdog sends "Feeder is back online."
