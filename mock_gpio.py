"""
Mock GPIO module for PetFeedr simulation mode.

This module mimics the RPi.GPIO interface so PetFeedr can run on non-Pi
hardware (laptops, desktops) for development and testing.
"""
import logging

# GPIO mode constants
BCM = "BCM"
BOARD = "BOARD"

# Pin direction constants
OUT = "OUT"
IN = "IN"

# Pin state constants
HIGH = 1
LOW = 0


def setmode(mode):
    """Set the GPIO numbering mode."""
    logging.debug(f"[SIM] GPIO.setmode({mode})")


def setwarnings(flag):
    """Enable or disable GPIO warnings."""
    logging.debug(f"[SIM] GPIO.setwarnings({flag})")


def setup(pin, direction, initial=None, pull_up_down=None):
    """Configure a GPIO pin."""
    if isinstance(pin, (list, tuple)):
        for p in pin:
            logging.debug(f"[SIM] GPIO.setup(pin={p}, direction={direction})")
    else:
        logging.debug(f"[SIM] GPIO.setup(pin={pin}, direction={direction})")


def output(pin, value):
    """Set a GPIO pin output value."""
    if isinstance(pin, (list, tuple)):
        for i, p in enumerate(pin):
            v = value[i] if isinstance(value, (list, tuple)) else value
            logging.debug(f"[SIM] GPIO.output(pin={p}, value={v})")
    else:
        logging.debug(f"[SIM] GPIO.output(pin={pin}, value={value})")


def input(pin):
    """Read a GPIO pin value (always returns LOW in simulation)."""
    logging.debug(f"[SIM] GPIO.input(pin={pin}) -> 0")
    return LOW


def cleanup(pin=None):
    """Clean up GPIO resources."""
    if pin:
        logging.debug(f"[SIM] GPIO.cleanup(pin={pin})")
    else:
        logging.debug("[SIM] GPIO.cleanup()")


