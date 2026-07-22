"""Pushover notifications — fail-soft, stdlib only.

Credentials come from the environment (PUSHOVER_TOKEN / PUSHOVER_USER,
loaded via the systemd unit's EnvironmentFile on the Pi). Unconfigured
or failing notifications must never break a feeding, so send() never
raises.
"""

import logging
import os
import urllib.parse
import urllib.request

from DRV8825 import SIMULATION_MODE

log = logging.getLogger('petfeedr')

PUSHOVER_URL = 'https://api.pushover.net/1/messages.json'


def send(message, title='PetFeedr', priority=0):
    """Send a Pushover notification. Returns True on success, False if
    suppressed, unconfigured, or the request failed."""
    # Dev machines can have real Pushover creds in the shell env — a sim
    # run must never page a phone (learned when a mocked-jam test did).
    if SIMULATION_MODE and os.environ.get('PETFEEDR_NOTIFY_IN_SIM', '').lower() != 'true':
        log.info(f"[SIM] Suppressed notification: {title}: {message}")
        return False

    token = os.environ.get('PUSHOVER_TOKEN')
    user = os.environ.get('PUSHOVER_USER')
    if not token or not user:
        log.debug("Pushover not configured (PUSHOVER_TOKEN/PUSHOVER_USER unset) - skipping notification")
        return False

    try:
        data = urllib.parse.urlencode({
            'token': token,
            'user': user,
            'title': title,
            'message': message,
            'priority': priority,
        }).encode()
        with urllib.request.urlopen(PUSHOVER_URL, data=data, timeout=5) as resp:
            if resp.status == 200:
                return True
            log.warning(f"Pushover returned HTTP {resp.status}")
            return False
    except Exception as e:
        log.warning(f"Pushover notification failed: {e}")
        return False
