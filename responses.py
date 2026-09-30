"""JSON-or-HTML response helpers shared by the route modules.

The UI's fetch() calls ask for JSON; plain form posts (no JS) get text or a
redirect.
"""

from flask import jsonify, request


def wants_json():
    """Check if the client prefers a JSON response."""
    return request.accept_mimetypes.best_match(
        ['application/json', 'text/html']) == 'application/json'


def error_response(message, status):
    if wants_json():
        return jsonify({'success': False, 'message': message}), status
    return message, status
