"""Crash-safe file replacement for the Pi's state files.

open(path, 'w') truncates first and writes second — a power cut in
between leaves an empty feeding_schedules.txt, and the feeder then runs
an empty schedule without complaint. Writing a sibling temp file and
os.replace()-ing it over the original means a reader only ever sees the
old contents or the new, never a half-written file.
"""

import os
import tempfile


def write_atomic(path, text):
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix='.' + os.path.basename(path) + '.')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())  # SD cards cache writes; data must hit flash before the rename
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    # Persist the rename itself — without this a power cut can roll it back
    dir_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
