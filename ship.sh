#!/bin/bash
# Ship main's unpushed commits: tests → PR → merge → deploy → prod smoke.
# Usage: ./ship.sh [branch-name]   (default: slug of the newest commit subject)
#        ./ship.sh --check         (preflight + smoke against the running Pi; changes nothing)
#
# Stops at the first failure. Never force-pushes. There's no CI in this repo,
# so the local test suite is the merge gate.

set -euo pipefail

PI_HOST="${PI_HOST:-jason@petfeedr}"
PI_PATH="${PI_PATH:-/home/jason/PetFeedr}"
FEED_GUARD_MIN=3  # a restart this close to a feed races it (catch-up covers it, but why test that)
cd "$(dirname "$0")"

say()  { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# Filter the Pi's locale noise from stderr only — piping stdout through grep
# would replace ssh's exit status with grep's, and `pi "grep -q …"` checks
# depend on the remote status
pi() { ssh -o ConnectTimeout=10 "$PI_HOST" "$@" 2> >(grep -v 'setlocale' >&2); }

feed_guard() {
    say "Checking the Pi's schedule for an imminent feed"
    local soon
    soon=$(pi "cat $PI_PATH/todays_schedule.json" | python3 -c '
import json, sys
from datetime import datetime
now = datetime.now()
data = json.load(sys.stdin)
for e in data.get("schedule", []):
    h, m = map(int, e["actual_time"].split(":"))
    delta = (now.replace(hour=h, minute=m, second=0, microsecond=0) - now).total_seconds() / 60
    if -1 <= delta <= '"$FEED_GUARD_MIN"':
        print(e["actual_time"])
') || fail "Couldn't read the Pi's schedule"
    [ -z "$soon" ] || fail "Feed due at $soon — wait until it has fired, then re-run"
    echo "  clear"
}

smoke() {
    say "Smoke-testing production"
    local ok=""
    for _ in 1 2 3 4 5; do
        [ "$(pi 'systemctl is-active petfeedr' | tail -1)" = "active" ] && { ok=1; break; }
        sleep 2
    done
    [ -n "$ok" ] || fail "petfeedr.service is not active: ssh $PI_HOST 'journalctl -u petfeedr -n 40'"
    echo "  service active"

    # systemd reports "active" a second or two before Flask is listening;
    # a single curl in that gap gets 000 (connection refused) — retry
    local code=""
    for _ in 1 2 3 4 5; do
        code=$(pi "curl -s -o /tmp/ship-idx.html -w '%{http_code}' localhost:5000/" | tail -1) || true
        [ "$code" = "200" ] && break
        sleep 2
    done
    [ "$code" = "200" ] || fail "Dashboard returned HTTP $code"
    echo "  dashboard 200"

    # Simulation on the Pi means the motor isn't driven — the worst silent failure.
    # Two independent checks, both fail-closed (logic + tests: ops/check_live.py).
    # 1) What the app reports. curl -f: a 404 (prod older than /api/state) or any
    #    error yields an empty body, which the checker rejects
    local verdict
    verdict=$(pi "curl -sf localhost:5000/api/state" | python3 ops/check_live.py --state) \
        || fail "Simulation check (state API): $verdict — if prod predates 1.5.0 this is expected before the first deploy"
    echo "  $verdict"
    # 2) The cause itself: the override in the running service's environment.
    #    Only the PETFEEDR_SIMULATE line leaves the Pi — the environ holds secrets
    verdict=$(pi 'P=$(systemctl show -p MainPID --value petfeedr); [ "${P:-0}" -gt 0 ] && [ -r /proc/$P/environ ] && { echo READABLE; tr "\0" "\n" < /proc/$P/environ | grep "^PETFEEDR_SIMULATE=" || true; }' \
        | python3 ops/check_live.py --env) \
        || fail "Simulation check (service env): $verdict"
    echo "  $verdict"

    local since
    since=$(pi "systemctl show petfeedr -p ActiveEnterTimestamp --value" | tail -1)
    if pi "sudo journalctl -u petfeedr --since '$since' --no-pager" | grep -q 'Traceback'; then
        fail "Traceback since the service started: ssh $PI_HOST 'journalctl -u petfeedr --since \"$since\"'"
    fi
    echo "  no tracebacks since start ($since)"
}

if [ "${1:-}" = "--check" ]; then
    feed_guard
    smoke
    say "Check passed — nothing was changed"
    exit 0
fi

# ---- Preflight: nothing leaves this machine until all of it passes ---------
say "Preflight"
[ "$(git branch --show-current)" = "main" ] || fail "Not on main"
[ -z "$(git status --porcelain)" ] || fail "Working tree isn't clean"
git fetch -q origin
[ "$(git rev-list --count origin/main..HEAD)" -gt 0 ] || fail "Nothing to ship — main matches origin/main"
[ "$(git rev-list --count HEAD..origin/main)" -eq 0 ] || fail "origin/main has commits you don't — pull first"
RANGE="origin/main..HEAD"
git log --oneline "$RANGE"

BRANCH="${1:-$(git log -1 --format=%s | sed -E 's/^[a-z]+(\([^)]*\))?: *//' \
    | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | cut -c1-40 | sed 's/-*$//')}"
# Re-running after a partial ship is fine if the branch is exactly this HEAD
REMOTE_SHA=$(git ls-remote --heads origin "$BRANCH" | cut -f1)
if [ -n "$REMOTE_SHA" ] && [ "$REMOTE_SHA" != "$(git rev-parse HEAD)" ]; then
    fail "Branch $BRANCH already exists on origin at a different commit"
fi

say "Running tests"
python3 -m unittest -q 2>&1 | tail -3
python3 -m unittest -q >/dev/null 2>&1 || fail "Tests failed"

feed_guard
PLIST_CHANGED=$(git diff --name-only "$RANGE" -- ops/mini-sync/city.marsh.petfeedr-sync.plist)

# ---- Ship -------------------------------------------------------------------
say "Pushing $BRANCH and opening the PR"
[ -n "$REMOTE_SHA" ] || git push -q origin "HEAD:refs/heads/$BRANCH"
# Title/body from the commits here — gh's --fill needs a local branch ref,
# and ship.sh pushes HEAD without creating one
if [ "$(git rev-list --count "$RANGE")" -eq 1 ]; then
    TITLE=$(git log -1 --format=%s)
    BODY=$(git log -1 --format=%b)
else
    TITLE="Ship: $(git log -1 --format=%s) (+$(( $(git rev-list --count "$RANGE") - 1 )) more)"
    BODY=$(git log --reverse --format='- %s' "$RANGE")
fi
BODY="$BODY

Local test suite passed (no CI in this repo). Shipped with ship.sh."
if gh pr view "$BRANCH" --json state -q .state 2>/dev/null | grep -q OPEN; then
    echo "  PR already open"
else
    gh pr create --base main --head "$BRANCH" --title "$TITLE" --body "$BODY"
fi
gh pr merge "$BRANCH" --merge --delete-branch
git pull -q --ff-only origin main
git branch -q -u origin/main

say "Deploying"
./deploy.sh

if [ -n "$PLIST_CHANGED" ]; then
    say "Reloading the mini's sync job (plist changed)"
    cp ops/mini-sync/city.marsh.petfeedr-sync.plist ~/Library/LaunchAgents/
    launchctl bootout "gui/$(id -u)/city.marsh.petfeedr-sync" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/city.marsh.petfeedr-sync.plist
fi

smoke
say "Shipped $(git log -1 --format=%h) ✓"
