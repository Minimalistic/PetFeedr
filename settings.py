"""Settings management for PetFeedr."""
import json
import os
import logging

SETTINGS_FILE = 'settings.json'

# Default settings
DEFAULT_SETTINGS = {
    'randomness_enabled': False,
    'randomness_range_minutes': 30,
}


def load_settings():
    """Load settings from file, or return defaults if not found."""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                # Merge with defaults to ensure all keys exist
                return {**DEFAULT_SETTINGS, **settings}
        except Exception as e:
            logging.error(f"Error loading settings: {e}")
    return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    """Save settings to file."""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception as e:
        logging.error(f"Error saving settings: {e}")
        return False


def get_setting(key, default=None):
    """Get a single setting value."""
    settings = load_settings()
    return settings.get(key, default)


def set_setting(key, value):
    """Set a single setting value."""
    settings = load_settings()
    settings[key] = value
    return save_settings(settings)
