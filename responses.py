"""JSON-or-HTML response helpers shared by the route modules.

The UI's fetch() calls ask for JSON; plain form posts (no JS) get text or a
redirect.
"""

from flask import jsonify, redirect, request

from feeder_core import log
import view_state


def wants_json():
    """Check if the client prefers a JSON response."""
    return request.accept_mimetypes.best_match(
        ['application/json', 'text/html']) == 'application/json'


def error_response(message, status):
    if wants_json():
        return jsonify({'success': False, 'message': message}), status
    return message, status


def success_response(message):
    """A completed change: JSON callers get the fresh dashboard state with it,
    so the UI updates in place instead of reloading."""
    if not wants_json():
        return redirect('/')
    body = {'success': True, 'message': message}
    # The change already landed — a failure building the snapshot must not
    # turn it into an error response; the client refetches /api/state instead
    try:
        body['state'] = view_state.build()
    except Exception as e:
        log.error(f"Couldn't build dashboard state after '{message}': {e}")
    return jsonify(body)
