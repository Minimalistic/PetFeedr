# PetFeedr → Mac mini → Obsidian

The Pi keeps 14 days of logs and a running hopper counter. That is fine
for the dashboard and useless for looking at a year of feeding. This
job makes the mini the durable copy and renders a note the vault (and
anything reading the vault) can use.

Chain, every 15 minutes, one-way:

```
Pi ~/PetFeedr/feeding_events.jsonl   append-only journal (events.py), never rotated
   ~/PetFeedr/hopper.json            counter + learned capacity
   ~/PetFeedr/feeding_schedules.txt  the schedule (kept for SD-card restores)
   ~/PetFeedr/todays_schedule.json   today's rolled times (the watchdog checks against it)
   ~/PetFeedr/feeding_log.txt*       14-day rotating human log
  → sync-petfeedr-mini.sh   launchd city.marsh.petfeedr-sync @15m on the mini
  → ~/.petfeedr-data/       state files overwritten; logs/ accumulates forever;
                            last_contact stamped on every successful pull
  → render_note.py          hourly: merges journal + log archives (dedup on the overlap day)
  → iCloud vault JasonWiki/Home/PetFeedr Feeding Log.md   (generated — edits get clobbered)
  → watchdog.py             every run, even when the pull failed: Pushover alerts
```

`render_note.py` imports the feeder's own log regexes from
`feeding_stats.py`, so log parsing can't drift from the device's. It
skips journal events tagged `sim` (dev-box runs). Everything is stdlib.

## Watchdog

The Pi can page about failures it can see. It can't page about its own
death. `watchdog.py` alerts once per incident (state in
`watchdog_state.json` in the store) when:

- **unreachable**: no successful pull for 45 min. Sends "back online" on recovery.
- **stale**: today's schedule wasn't rolled over by 00:15, so the service is down.
- **missed**: a scheduled time is 15+ min past with no dispense or failure event.
- **simulation**: the Pi's journal has `sim` events today, so the motor isn't driven.

Pushover creds come from `~/.config/petfeedr/pushover.env` (override with
`PETFEEDR_ALERT_ENV`), because launchd doesn't inherit shell exports. The
file holds `PUSHOVER_TOKEN=…` and `PUSHOVER_USER=…`, mode 600. Without it,
alerts print as `UNSENT` in the sync log and are retried on the next run.

## Install (mini, as jason)

```bash
cp ops/mini-sync/city.marsh.petfeedr-sync.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/501 ~/Library/LaunchAgents/city.marsh.petfeedr-sync.plist
```

SSH to `jason@petfeedr` must work non-interactively (it does; deploy.sh
uses the same host). Override with `PI_HOST`; `PETFEEDR_STORE` moves the
local store.

## Verify

```bash
launchctl kickstart gui/501/city.marsh.petfeedr-sync
tail -3 ~/Library/Logs/petfeedr-sync.log
```

Expect `rendered N feedings → .../PetFeedr Feeding Log.md` (at most hourly)
and no `UNSENT` or `pull … failed` lines. Run the
script by hand for the same effect. To re-render without touching the
Pi: `python3 ops/mini-sync/render_note.py ~/.petfeedr-data`.

## Remove

```bash
launchctl bootout gui/501/city.marsh.petfeedr-sync
rm ~/Library/LaunchAgents/city.marsh.petfeedr-sync.plist
```

The store in `~/.petfeedr-data/` is the history — keep it.
