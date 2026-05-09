"""
pansyncer mouse.py
Probes for mice, polls their FDs to change frequency and step cycles.
"""

import evdev

class MouseState:
    """Discovery and event handling for mouse - reads all available mice."""
    def __init__(self, now, logger, display=None):
        self.display = display
        self.logger = logger
        self.mice = []
        self._discover_devices()
        self.last_scroll_time = now

    def _discover_devices(self):
        """Scan for matching input devices, add new ones, and remove disappeared ones."""
        paths = list(evdev.list_devices())
        current_paths = set(paths)

        existing_by_path = {}
        for dev in list(self.mice):
            path = getattr(dev, "path", None)
            if path is None or path not in current_paths:
                try:
                    dev.close()
                except OSError:
                    pass
                continue

            if path in existing_by_path:
                try:
                    dev.close()
                except OSError:
                    pass
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
                has_wheel = (evdev.ecodes.EV_REL in caps
                    and evdev.ecodes.REL_WHEEL in caps[evdev.ecodes.EV_REL])
                has_click = ( evdev.ecodes.EV_KEY in caps
                    and evdev.ecodes.BTN_MIDDLE in caps[evdev.ecodes.EV_KEY])
                if has_wheel or has_click:
                    found.append(dev)
                    self.logger.log(f"Mouse found: {dev.name}", "INFO")
                    keep = True

            except (OSError, evdev.UInputError) as e:
                self.logger.log(f"Failed discovering Mouse: {e}", "ERROR")
            finally:
                if dev is not None and not keep:
                    try:
                        dev.close()
                    except OSError:
                        pass
        self.mice = found
        if self.display:
            self.display.set_mouse(bool(self.mice))

    def ensure_connected(self):
        """Re-scan devices and return True if at least one mouse is tracked."""
        self._discover_devices()
        return bool(self.mice)

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

    def refresh(self):
        """Close tracked mouse devices and rescan without disabling the logical device."""
        for dev in list(self.mice):
            try:
                dev.close()
            except OSError as e:
                self.logger.log(f"Failed to close mouse device {e}", "WARN")

        self.mice.clear()
        self._discover_devices()
        return bool(self.mice)

    def get_fds(self):
        """Return a list of file descriptors to poll."""
        return [dev.fd for dev in self.mice]

    def handle_event(self, fd, sync, step, now):
        """Process all pending wheel or middle-click events for the given fd."""
        dev = next((d for d in self.mice if d.fd == fd), None)
        if not dev:
            return
        try:
            for event in dev.read():
                if event.type == evdev.ecodes.EV_REL and event.code == evdev.ecodes.REL_WHEEL:
                    if event.value == 0:
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
                elif event.type == evdev.ecodes.EV_KEY and event.code == evdev.ecodes.BTN_MIDDLE and event.value == 1:
                    step.next_step()
                    if self.display:
                        self.display.set_step_value(step.get_step())
                    if self.display:
                        self.display.set_mouse_input("STP")
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