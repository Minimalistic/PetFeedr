# PetFeedr → Mac mini → Obsidian

The Pi keeps 14 days of logs and a running hopper counter. That is fine
for the dashboard and useless for looking at a year of feeding. This
job makes the mini the durable copy and renders a note the vault (and
anything reading the vault) can use.

Chain, hourly, one-way:

```
Pi ~/PetFeedr/feeding_events.jsonl   append-only journal (events.py), never rotated
   ~/PetFeedr/hopper.json            counter + learned capacity
   ~/PetFeedr/feeding_log.txt*       14-day rotating human log
  → sync-petfeedr-mini.sh   launchd city.marsh.petfeedr-sync @1h on the mini
  → ~/.petfeedr-data/       journal + hopper.json overwritten; logs/ accumulates forever
  → render_note.py          merges journal + log archives (dedup on the overlap day)
  → iCloud vault JasonWiki/Home/PetFeedr Feeding Log.md   (generated — edits get clobbered)
```

`render_note.py` imports the feeder's own log regexes from
`feeding_stats.py`, so log parsing can't drift from the device's. It
skips journal events tagged `sim` (dev-box runs). Everything is stdlib.

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

Expect `rendered N feedings → .../PetFeedr Feeding Log.md`. Run the
script by hand for the same effect. To re-render without touching the
Pi: `python3 ops/mini-sync/render_note.py ~/.petfeedr-data`.

## Remove

```bash
launchctl bootout gui/501/city.marsh.petfeedr-sync
rm ~/Library/LaunchAgents/city.marsh.petfeedr-sync.plist
```

The store in `~/.petfeedr-data/` is the history — keep it.
