"""
pansyncer evdev_hotplug.py
inotify wrapper for /dev/input hotplug events.
"""

import ctypes
import errno
import os
import struct
from dataclasses import dataclass


IN_ATTRIB = 0x00000004
IN_MOVED_FROM = 0x00000040
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
IN_DELETE = 0x00000200
IN_DELETE_SELF = 0x00000400
IN_MOVE_SELF = 0x00000800
IN_Q_OVERFLOW = 0x00004000
IN_IGNORED = 0x00008000

WATCH_MASK = (
    IN_ATTRIB
    | IN_CREATE
    | IN_DELETE
    | IN_MOVED_FROM
    | IN_MOVED_TO
    | IN_DELETE_SELF
    | IN_MOVE_SELF
    | IN_Q_OVERFLOW
    | IN_IGNORED
)


@dataclass
class InputHotplugConfig:
    """Default evdev hotplug configuration."""

    enabled: bool = True
    path: str = "/dev/input"
    watchdog_interval: float = 3.0
    watchdog_backoff_cap: float = 9.0
    retry_delay: float = 0.25
    mouse_watchdog_enabled: bool = True


@dataclass(frozen=True)
class EvdevHotplugEvent:
    """One parsed inotify event for /dev/input."""

    name: str
    mask: int
    action: str


class EvdevHotplugMonitor:
    """Watch /dev/input and expose an fd suitable for select()."""

    def __init__(self, logger=None, cfg=None):
        self.logger = logger
        self.cfg = cfg or InputHotplugConfig()
        self.path = self.cfg.path
        self._fd = None
        self._wd = None
        self._libc = None

        if self.cfg.enabled:
            self._start()
        else:
            self._log("evdev hotplug disabled by config", "DEBUG")

    def active(self):
        """Return True if the monitor has a usable fd."""
        return self._fd is not None

    def fd(self):
        """Return the inotify fd, or None if monitoring is unavailable."""
        return self._fd

    def close(self):
        """Close the inotify fd."""
        if self._fd is None:
            return

        fd = self._fd
        self._fd = None
        self._wd = None

        try:
            os.close(fd)
        except OSError as e:
            self._log(f"evdev hotplug close error: {e}", "DEBUG")

    def drain(self):
        """Drain pending inotify events and return relevant parsed events."""
        if self._fd is None:
            return []

        chunks = []
        while True:
            try:
                chunk = os.read(self._fd, 4096)
            except BlockingIOError:
                break
            except OSError as e:
                if getattr(e, "errno", None) in (errno.EAGAIN, errno.EWOULDBLOCK):
                    break
                self._log(f"evdev hotplug read error: {e}", "DEBUG")
                self.close()
                break

            if not chunk:
                break

            chunks.append(chunk)

            if len(chunk) < 4096:
                break

        if not chunks:
            return []

        events = []
        for chunk in chunks:
            events.extend(self._parse_events(chunk))

        return [
            event for event in events
            if self.is_relevant_event(event)
        ]

    @staticmethod
    def is_relevant_event(event):
        """Return True if an event should trigger input device rediscovery."""
        if event.mask & (IN_Q_OVERFLOW | IN_DELETE_SELF | IN_MOVE_SELF | IN_IGNORED):
            return True
        return event.name.startswith("event")

    @staticmethod
    def _parse_events(data):
        """Parse raw inotify_event structures."""
        events = []
        offset = 0
        header_size = struct.calcsize("iIII")

        while offset + header_size <= len(data):
            _wd, mask, _cookie, name_len = struct.unpack_from("iIII", data, offset)
            offset += header_size

            raw_name = data[offset:offset + name_len]
            offset += name_len

            name = raw_name.split(b"\0", 1)[0].decode("utf-8", "replace")
            events.append(EvdevHotplugEvent(name=name, mask=mask, action=_action_from_mask(mask)))

        return events

    def _start(self):
        """Open inotify and watch the configured input device path."""
        if not os.path.isdir(self.path):
            self._log(f"evdev hotplug disabled: {self.path} not found", "DEBUG")
            return

        try:
            libc = ctypes.CDLL(None, use_errno=True)
            libc.inotify_init1.argtypes = [ctypes.c_int]
            libc.inotify_init1.restype = ctypes.c_int
            libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
            libc.inotify_add_watch.restype = ctypes.c_int

            fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
            if fd < 0:
                err = ctypes.get_errno()
                raise OSError(err, os.strerror(err))

            wd = libc.inotify_add_watch(fd, self.path.encode(), WATCH_MASK)
            if wd < 0:
                err = ctypes.get_errno()
                try:
                    os.close(fd)
                except OSError:
                    pass
                raise OSError(err, os.strerror(err))

            self._libc = libc
            self._fd = fd
            self._wd = wd
            self._log(f"evdev hotplug monitor active on {self.path}", "DEBUG")

        except Exception as e:
            self._fd = None
            self._wd = None
            self._libc = None
            self._log(f"evdev hotplug disabled: {e}", "DEBUG")

    def _log(self, msg, level="DEBUG"):
        if self.logger:
            self.logger.log(msg, level)


def _action_from_mask(mask):
    """Return a compact human-readable action label."""
    if mask & IN_Q_OVERFLOW:
        return "overflow"
    if mask & (IN_DELETE_SELF | IN_MOVE_SELF | IN_IGNORED):
        return "watch-reset"
    if mask & (IN_CREATE | IN_MOVED_TO):
        return "add"
    if mask & (IN_DELETE | IN_MOVED_FROM):
        return "remove"
    if mask & IN_ATTRIB:
        return "attrib"
    return "change"