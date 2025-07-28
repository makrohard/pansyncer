"""
pansyncer mouse.py
Probes for mice, polls their FDs to change frequency and step cycles.
"""

import evdev

class MouseState:
    """ Discovery and event handling for mouse - reads all available mice """
    def __init__(self, now, logger, display=None):
        self.display = display
        self.logger = logger
        self.mice = []
        self._discover_devices() # initial discovery
        self.last_scroll_time = now

    def _discover_devices(self):
        """Scan for input devices supporting wheel or middle-click."""
        found = []
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
                caps = dev.capabilities()
                has_wheel = evdev.ecodes.EV_REL in caps and \
                            evdev.ecodes.REL_WHEEL in caps[evdev.ecodes.EV_REL]
                has_click = evdev.ecodes.EV_KEY in caps and \
                            evdev.ecodes.BTN_MIDDLE in caps[evdev.ecodes.EV_KEY]
                if has_wheel or has_click:
                    found.append(dev)
                    self.logger.log(f"Mouse found: {dev.name}", "INFO")

            except (OSError, evdev.UInputError) as e:
                self.logger.log(f"Failed discovering Mouse: {e}", "ERROR")
                continue
        self.mice = found
        if self.display: self.display.set_mouse(bool(self.mice))

    def ensure_connected(self):
        """Re-scan if no devices are currently tracked."""
        # FIXME Will not trigger if knob is connected, because knob its presenting a unused mouse device
        if not self.mice:
            self._discover_devices()

    def disconnect(self):
        """Close all tracked devices and clear state."""
        for dev in list(self.mice):
            try:
                dev.close()
            except OSError as e:
                self.logger.log(f"Failed to close mouse device {e}", "WARN")
        self.mice.clear()
        if self.display: self.display.set_mouse(False)
        self.logger.log(f"Mouse disabled", "INFO")

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
                    self.last_scroll_time = now
                    if event.value > 0:
                        sync.nudge(step.get_step())
                        if self.display: self.display.set_mouse_input("UP ")
                    else:
                        sync.nudge(-step.get_step())
                        if self.display: self.display.set_mouse_input("DWN")
                elif event.type == evdev.ecodes.EV_KEY and event.code == evdev.ecodes.BTN_MIDDLE and event.value == 1:
                    step.next_step()
                    if self.display: self.display.set_step_value(step.get_step())
                    if self.display: self.display.set_mouse_input("STP")
        except OSError as e:
            self.logger.log(f"Mouse events {e}", "ERROR")
            try:                                                                    # on error, close and remove device
                dev.close()
            except OSError:
                pass
            self.mice.remove(dev)
            if self.display:
                if self.display: self.display.set_mouse(False)
                self.logger.log(f"Mouse disconnected: {dev.name}", "INFO")
