"""
pansyncer utils.py
"""

import sys

def beep():
    """ Send ANSI BEL to terminal."""
    out = sys.stdout
    if not getattr(out, "isatty", lambda: False)():
        return False
    try:
        print("\a", end="", flush=True, file=out)
    except (OSError, ValueError):
        return False
    return True