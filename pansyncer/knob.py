"""
pansyncer knob.py
Expects to have an External VFO Knob (External volume Knob) configured .
Grabs the first matching device and maps the reported key to Frequency / Step changes.
"""

import errno
from dataclasses import dataclass
from typing import List

from evdev import InputDevice, list_devices, ecodes


@dataclass
class KnobConfig:
    """Default configuration (fallback)"""
    # Device Identification
    target_name: str = "Wired KeyBoard Consumer Control"
    target_vendor: int = 0x05ac
    target_product: int = 0x0202
    # Key mappings
    key_up: int = ecodes.KEY_VOLUMEUP
    key_down: int = ecodes.KEY_VOLUMEDOWN
    key_step: int = ecodes.KEY_MUTE


DEFAULT_KNOB_CONFIGS: List[KnobConfig] = [KnobConfig()]


class KnobController:
    """Connection handling and event reading for external VFO device."""

    def __init__(self, cfg, logger, display=None):
        self.cfg = cfg
        self.display = display
        self.logger = logger
        self.dev = None
        self.active_cfg = None
        if not hasattr(self.cfg, "knobs") or not self.cfg.knobs:
            self.cfg.knobs = DEFAULT_KNOB_CONFIGS

    def ensure_connected(self):
        """Grab device, if found."""
        if self.dev:
            if self._device_path_still_present():
                return True
            self.disconnect()

        self.dev = self._find_input_device()
        if not self.dev:
            return False

        if self.display:
            self.display.set_knob(True)
        self.logger.log(f"VFO-Knob connected: {self.dev.name}", "INFO")
        return True

    def disconnect(self):
        """Release grab, close device and reset state."""
        if not self.dev:
            return

        dev = self.dev

        try:
            dev.ungrab()
            self.logger.log("Ungrabbed device KNOB ", "DEBUG")
        except OSError as e:
            self.logger.log(f"Failed to ungrab device KNOB {e}", "DEBUG")

        try:
            dev.close()
        except OSError as e:
            self.logger.log(f"Failed to close device KNOB {e}", "DEBUG")

        self.dev = None
        self.active_cfg = None

        if self.display:
            self.display.set_knob(False)

        self.logger.log("VFO-Knob disconnected", "INFO")

    def fd(self):
        """Return file descriptor."""
        return self.dev.fd if self.dev else None

    def handle_events(self, sync, step):
        """Read pending events and dispatch mapped actions."""
        if not self.dev or not self.active_cfg:
            return

        try:
            for event in self.dev.read():
                if event.type != ecodes.EV_KEY or event.value != 1:
                    continue

                if event.code == self.active_cfg.key_up:
                    sync.nudge(step.get_step())
                    if self.display:
                        self.display.set_step_value(step.get_step())
                    if self.display:
                        self.display.set_knob_input("UP ")

                elif event.code == self.active_cfg.key_down:
                    sync.nudge(-step.get_step())
                    if self.display:
                        self.display.set_step_value(step.get_step())
                    if self.display:
                        self.display.set_knob_input("DWN")

                elif event.code == self.active_cfg.key_step:
                    step.next_step()
                    if self.display:
                        self.display.set_step_value(step.get_step())
                    if self.display:
                        self.display.set_knob_input("STP")

        except (OSError, IOError, ValueError) as e:                                    # On error, fully reset connection
            self.logger.log(f"Failed reading knob events: {e}", "WARNING")
            self.disconnect()

    def _device_path_still_present(self):
        """Return True if the currently opened evdev path still exists."""
        if not self.dev:
            return False

        path = getattr(self.dev, "path", None)
        if not path:
            return True

        try:
            return path in set(list_devices())
        except OSError as e:
            self.logger.log(f"Failed checking knob devices: {e}", "DEBUG")
            return True

    def _find_input_device(self):
        """Iterate through all knob configs and return the first matching grabbed device."""
        for knob_cfg in self.cfg.knobs:
            dev = self._probe_device(knob_cfg, self.logger)
            if dev:
                self.active_cfg = knob_cfg
                return dev

        self.logger.log("No matching knob device found.", "DEBUG")
        return None

    @classmethod
    def _probe_device(cls, knob_cfg, logger):
        """Scan for devices and return matching grabbed VFO InputDevice or None."""
        for path in list_devices():
            dev = None
            keep = False

            try:
                dev = InputDevice(path)

                matched = (
                    dev.name == knob_cfg.target_name
                    and dev.info.vendor == knob_cfg.target_vendor
                    and dev.info.product == knob_cfg.target_product
                )

                if not matched:
                    continue

                caps = dev.capabilities().get(ecodes.EV_KEY, [])
                if knob_cfg.key_up not in caps or knob_cfg.key_down not in caps:
                    logger.log(
                        f"Device {dev.name} ignored (missing key_up/down capabilities)",
                        "DEBUG",
                    )
                    continue

                try:
                    dev.grab()
                except OSError as e:
                    if getattr(e, "errno", None) == errno.EBUSY:
                        logger.log(f"Failed to grab knob {path}: device busy", "DEBUG")
                    else:
                        logger.log(f"Failed to grab knob {path}: {e}", "WARN")
                    continue

                logger.log(f"VFO-Knob found: {dev.name}", "DEBUG")
                keep = True
                return dev

            except OSError as e:
                logger.log(f"Error accessing KNOB {path}: {e}", "WARN")

            finally:
                if dev is not None and not keep:
                    try:
                        dev.close()
                    except OSError:
                        pass

        return None