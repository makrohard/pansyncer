"""
pansyncer logger.py
Uses python logging to write to display. Optional file logging.
"""

import sys
import logging

class DisplayLogHandler(logging.Handler):
    """Custom logging handler that sends log messages to a display object."""

    def __init__(self, display):
        super().__init__()
        self.display = display

    def emit(self, record):
        try:
            msg = self.format(record)
            if self.display:
                self.display.log(msg)
            elif record.levelno >= logging.WARNING:                               # Fallback to stderr if display is off
                print(f"[PANSYNCER ERROR]: {msg}", file=sys.stderr)
        except (AttributeError, TypeError, ValueError) as e:
            print(f"[PANSYNCER LOGGER ERROR] {e}", file=sys.stderr)

class Logger:
    """Writes to display, optionally to a log file."""

    def __init__(self, name, display=None, level='INFO', logfile_path=None):
        self.display = display
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level.upper())
        self.logger.propagate = False

        formatter = logging.Formatter('[%(levelname)s] %(message)s')

        display_handler = DisplayLogHandler(display)                                                # Log to display
        display_handler.setFormatter(formatter)
        self.logger.addHandler(display_handler)

        self.file_handler = None
        if logfile_path:                                                                            # Log to file
            try:
                self.file_handler = logging.FileHandler(logfile_path, mode='a', encoding='utf-8')
                self.file_handler.setFormatter(formatter)
                self.logger.addHandler(self.file_handler)
                if self.display: self.display.log(f"[LOGGER] Logging to file: {logfile_path}")
            except OSError as e:
                if self.display: self.display.log(f"[LOGGER ERROR] Failed to write log file: {e}")

    def log(self, msg, level='INFO'):
        """Log a message at a given level."""
        self.logger.log(getattr(logging, level.upper(), logging.INFO), msg)

    def close(self):
        """Close all handlers."""
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)
        try:
            self.file_handler = None
        except AttributeError:
            pass
