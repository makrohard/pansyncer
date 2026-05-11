"""
pansyncer mouse.py
Probes for mice, polls their FDs to change frequency and step cycles.
"""

import os
import time

import evdev


class MouseState:
    """Discovery and event handling for mouse - reads all available mice."""

    def __init__(self, now, logger, display=None, fullscan_interval=9.0):
        self.display = display
        self.logger = logger
        self.mice = []
        self.last_scroll_time = now
        self._last_discovery = None
        self._fullscan_interval = max(0.0, float(fullscan_interval))
        self._discover_devices(now=now)

    def _close_device(self, dev):
        """Close an evdev device, ignoring close errors."""
        try:
            dev.close()
        except OSError:
            pass

    def _prune_missing_devices(self):
        """Keep opened mouse devices whose event path still exists."""
        changed = False
        found = []
        seen_paths = set()

        for dev in list(self.mice):
            path = getattr(dev, "path", None)

            if path is not None:
                if path in seen_paths or not os.path.exists(path):
                    self._close_device(dev)
                    changed = True
                    continue

                seen_paths.add(path)

            found.append(dev)

        if changed:
            self.mice = found
            if self.display:
                self.display.set_mouse(bool(self.mice))

        return bool(self.mice)

    def _discover_devices(self, now=None):
        """Scan for matching input devices, add new ones, and remove disappeared ones."""
        if now is None:
            now = time.monotonic()

        paths = list(evdev.list_devices())
        current_paths = set(paths)

        existing_by_path = {}
        for dev in list(self.mice):
            path = getattr(dev, "path", None)

            if path is None or path not in current_paths:
                self._close_device(dev)
                continue

            if path in existing_by_path:
                self._close_device(dev)
                continue

            existing_by_path[path] = dev

        found = []
        seen_paths = set()

        for path in paths:
            if path in seen_paths:
                continue
            seen_paths.add(path)

            if path in existing_by_path:
                found.append(existing_by_path[path])
                continue

            dev = None
            keep = False

            try:
                dev = evdev.InputDevice(path)
                caps = dev.capabilities()

                has_wheel = (
                    evdev.ecodes.EV_REL in caps
                    and evdev.ecodes.REL_WHEEL in caps[evdev.ecodes.EV_REL]
                )
                has_click = (
                    evdev.ecodes.EV_KEY in caps
                    and evdev.ecodes.BTN_MIDDLE in caps[evdev.ecodes.EV_KEY]
                )

                if has_wheel or has_click:
                    found.append(dev)
                    self.logger.log(f"Mouse found: {dev.name} ({dev.path})", "INFO")
                    keep = True

            except (OSError, evdev.UInputError) as e:
                self.logger.log(f"Failed discovering Mouse: {e}", "ERROR")
            finally:
                if dev is not None and not keep:
                    self._close_device(dev)

        self.mice = found
        self._last_discovery = now

        if self.display:
            self.display.set_mouse(bool(self.mice))

    def ensure_connected(self, force=False, now=None):
        """Return True if at least one mouse is tracked, rescanning only when needed."""
        if now is None:
            now = time.monotonic()

        if force:
            self._discover_devices(now=now)
            return bool(self.mice)

        if not self._prune_missing_devices():
            self._discover_devices(now=now)
            return bool(self.mice)

        if (
            self._last_discovery is None
            or now - self._last_discovery >= self._fullscan_interval
        ):
            self._discover_devices(now=now)
            return bool(self.mice)

        return True

    def disconnect(self):
        """Close all tracked devices and clear state."""
        for dev in list(self.mice):
            try:
                dev.close()
            except OSError as e:
                self.logger.log(f"Failed to close mouse device {e}", "WARN")

        self.mice.clear()

        if self.display:
            self.display.set_mouse(False)

        self.logger.log("Mouse disabled", "INFO")

    def refresh(self, now=None, reset=False):
        """
        Rescan mouse devices.
        reset=False: Keep still-valid opened devices and add/remove by path.
        reset=True:  Close all opened devices first, then rebuild from scratch.
        """
        if reset:
            for dev in list(self.mice):
                try:
                    dev.close()
                except OSError as e:
                    self.logger.log(f"Failed to close mouse device {e}", "WARN")
            self.mice.clear()

        self._discover_devices(now=now)
        return bool(self.mice)

    def get_fds(self):
        """Return a list of file descriptors to poll."""
        return [dev.fd for dev in self.mice]



    def get_fds(self):
        """Return a list of file descriptors to poll."""
        return [dev.fd for dev in self.mice]


    def handle_event(self, fd, sync, step, now, active=True):
        """Drain pending mouse events for the given fd and dispatch relevant actions when active."""
        dev = next((d for d in self.mice if d.fd == fd), None)
        if not dev:
            return False

        had_action = False

        try:
            for event in dev.read():
                if event.type == evdev.ecodes.EV_SYN:
                    continue

                if event.type == evdev.ecodes.EV_REL and event.code == evdev.ecodes.REL_WHEEL:
                    if event.value == 0:
                        continue

                    if not active:
                        continue

                    self.last_scroll_time = now
                    if event.value > 0:
                        sync.nudge(step.get_step())
                        if self.display:
                            self.display.set_mouse_input("UP ")
                    else:
                        sync.nudge(-step.get_step())
                        if self.display:
                            self.display.set_mouse_input("DWN")

                    had_action = True

                elif (
                    event.type == evdev.ecodes.EV_KEY
                    and event.code == evdev.ecodes.BTN_MIDDLE
                    and event.value == 1
                ):
                    if not active:
                        continue

                    step.next_step()
                    if self.display:
                        self.display.set_step_value(step.get_step())
                        self.display.set_mouse_input("STP")

                    had_action = True

            return had_action

        except OSError as e:
            self.logger.log(f"Mouse events {e}", "ERROR")
            try:
                dev.close()
            except OSError:
                pass
            if dev in self.mice:
                self.mice.remove(dev)
            if self.display:
                self.display.set_mouse(bool(self.mice))
            self.logger.log(f"Mouse disconnected: {dev.name}", "INFO")
            return False
