"""
pansyncer knob.py
Expects to have an External VFO Knob (External volume Knob) configured .
Grabs the first matching device and maps the reported key to Frequency / Step changes.
"""

from evdev import InputDevice, list_devices, ecodes
from dataclasses import dataclass
from typing import List

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
    """ Connection handling and event reading for external VFO device. """

    def __init__(self, cfg, logger, display = None):
        self.cfg = cfg
        self.display = display
        self.logger = logger
        self.dev = None
        self.active_cfg = None
        if not hasattr(self.cfg, "knobs") or not self.cfg.knobs:
            self.cfg.knobs = DEFAULT_KNOB_CONFIGS

    def ensure_connected(self):
        """ Grab device, if found. """
        if self.dev:
            return
        self.dev = self._find_input_device()
        if not self.dev:
            return
        try:
            self.dev.grab()
            if self.display: self.display.set_knob(True)
            self.logger.log(f"VFO-Knob connected: {self.dev.name}", "INFO")
        except OSError as e:
            self.logger.log(f"Failed to grab device KNOB {e}", "WARN")
            self.dev = None

    def disconnect(self):
        """Release grab and reset state."""
        if not self.dev:
            return
        try:
            self.dev.ungrab()
            self.logger.log("Ungrabbed device KNOB ", "DEBUG")
            self.dev.close()
        except OSError as e:
            self.logger.log(f"Failed to ungrab device KNOB {e}", "DEBUG")
        self.dev = None

        if self.display: self.display.set_knob(False)
        self.active_cfg = None
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
                    if self.display: self.display.set_step_value(step.get_step())
                    if self.display: self.display.set_knob_input("UP ")

                elif event.code == self.active_cfg.key_down:
                    sync.nudge(-step.get_step())
                    if self.display: self.display.set_step_value(step.get_step())
                    if self.display: self.display.set_knob_input("DWN")

                elif event.code == self.active_cfg.key_step:
                    step.next_step()
                    if self.display: self.display.set_step_value(step.get_step())
                    if self.display: self.display.set_knob_input("STP")

        except (OSError, IOError) as e:                                              # On error, fully reset connection
            self.logger.log(f"Failed reading knob events: {e}", "WARNING")
            self.disconnect()

    def _find_input_device(self):
        """Iterate through all knob configs and return the first matching device."""
        for knob_cfg in self.cfg.knobs:
            dev = self._probe_device(knob_cfg, self.logger)
            if dev:
                self.active_cfg = knob_cfg
                return dev

        self.logger.log("No matching knob device found.", "DEBUG")
        return None

    @classmethod
    def _probe_device(cls, knob_cfg, logger):
        """Scan for devices and return matching VFO InputDevice or None."""
        #logger.log(f"Probing for knob: {knob_cfg.target_name} vendor={hex(knob_cfg.target_vendor)} product={hex(knob_cfg.target_product)}","DEBUG")
        for path in list_devices():
            try:
                dev = InputDevice(path)
                #logger.log(f"Checking device at {path}: name={dev.name} vendor={hex(dev.info.vendor)} product={hex(dev.info.product)}","DEBUG")
                if (dev.name == knob_cfg.target_name
                    and dev.info.vendor == knob_cfg.target_vendor
                    and dev.info.product == knob_cfg.target_product):

                    caps = dev.capabilities().get(ecodes.EV_KEY, [])
                    #logger.log(f"Capabilities for {dev.name}: {caps}", "DEBUG")
                    if knob_cfg.key_up in caps and knob_cfg.key_down in caps:
                        logger.log(f"VFO-Knob found: {dev.name}", "DEBUG")
                        return dev
                    else:
                        #logger.log(f"Device {dev.name} ignored (missing key_up/down capabilities)", "DEBUG")
                        logger.log(
                            f"Device {dev.name} ignored (missing key_up/down capabilities)",
                            "DEBUG",
                        )
            except OSError as e:
                logger.log(f"Error accessing KNOB {path}: {e}", "WARN")
                continue
        return None
