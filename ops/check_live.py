#!/usr/bin/env python3
"""Is the deployed feeder driving the real motor? Used by ship.sh's smoke test.

Simulation on the Pi means meals get logged that the motor never dispensed —
the worst silent failure, so both checks fail closed: only positive proof of
live mode passes, and anything missing or unreadable fails.

  --state  stdin is the Pi's /api/state body; passes only on
           "simulation": false.
  --env    stdin is "READABLE" (the service's /proc environ could be read)
           followed by any PETFEEDR_SIMULATE= line from it; passes only when
           readable and the override isn't set. Independent of the web layer:
           it checks the cause (the override DRV8825 honors), not a symptom.

The logic lives here, not inline in ship.sh, so test_feeder runs the same
functions against real /api/state output — a future change to the state
shape fails a unit test instead of quietly blinding the smoke test.
"""

import json
import sys


def state_is_live(body_text):
    """(ok, reason) for an /api/state response body."""
    try:
        body = json.loads(body_text)
        simulation = body['data']['app']['simulation']
    except (ValueError, KeyError, TypeError):
        return False, "couldn't read app.simulation from /api/state"
    if body.get('success') is not True:
        return False, '/api/state did not report success'
    if simulation is False:
        return True, 'live (state API)'
    return False, f'app.simulation is {simulation!r}'


def env_is_live(env_text):
    """(ok, reason) for the READABLE marker + PETFEEDR_SIMULATE lines."""
    lines = env_text.splitlines()
    if 'READABLE' not in lines:
        return False, "couldn't read the service's environment"
    for line in lines:
        if line.startswith('PETFEEDR_SIMULATE='):
            # Same parse as DRV8825: only "true" (any case) forces simulation
            if line.split('=', 1)[1].strip().lower() == 'true':
                return False, 'PETFEEDR_SIMULATE=true is set on the service'
    return True, 'live (no simulation override)'


def main():
    checks = {'--state': state_is_live, '--env': env_is_live}
    if len(sys.argv) != 2 or sys.argv[1] not in checks:
        print('usage: check_live.py --state|--env < input', file=sys.stderr)
        return 2
    ok, reason = checks[sys.argv[1]](sys.stdin.read())
    print(reason)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
