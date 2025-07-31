"""
pansyncer device_register.py
Tracks which peripherals are enabled, fires callbacks when devices are added or removed.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Set


@dataclass
class DeviceRegisterConfig:
    """Default configuration"""
    enabled: List[str] = field(default_factory=lambda: ["rig", "gqrx", "keyboard", "knob", "mouse"])
    device_map: Dict[str, str] = field(default_factory=lambda: {"r": "rig", "g": "gqrx", "k": "knob", "m": "mouse"})
    radios: Set[str] = field(default_factory=lambda: {"rig", "gqrx"})

class DeviceRegister:
    """Keeps track of enabled devices and notifies subscribers on changes."""

    def __init__(self, cfg, initial=None, logger=None):
        self.cfg = cfg
        if initial is not None:
            devs = set(initial)
        else:
            devs = set(cfg.devices.enabled)
            if not cfg.main.daemon:
                devs.add("keyboard")
        self._devices = devs
        self._on_add = []
        self._on_remove = []
        self.logger = logger


    @classmethod
    def from_args(cls, args):
        """ Construct a DeviceRegister from parsed CLI args. """
        cfg = DeviceRegisterConfig()
        enabled_devices = [cfg.device_map.get(d, d) for d in args.devices]
        cfg.enabled = enabled_devices
        return cls(cfg)

                                                                                                    # Subscription API
    def on_add(self, callback):
        """Register callback for device additions."""
        self._on_add.append(callback)

    def on_remove(self, callback):
        """Register callback for device removals."""
        self._on_remove.append(callback)
                                                                                                    # Mutation API
    def add(self, dev):
        """Enable a device and notify subscribers."""
        if dev not in self._devices:
            self._devices.add(dev)
            for fn in self._on_add:
                fn(dev)

    def remove(self, dev):
        """Disable a device and notify subscribers."""
        if dev in self._devices:
            self._devices.remove(dev)
            for fn in self._on_remove:
                fn(dev)

    def toggle(self, dev):
        """Toggle a device on/off."""
        # Prevent disabling both radios
        if dev in self.cfg.devices.radios and dev in self._devices:
            other = next(r for r in self.cfg.devices.radios if r != dev)
            if other not in self._devices:
                if self.logger: self.logger.log(f"Cannot disable both {dev} and {other}", "ERROR")
                return False
                                                                                                   # Perform the toggle
        if dev in self._devices:
            self.remove(dev)
        else:
            self.add(dev)
        return True
                                                                                                   # Query API
    def enabled(self, dev):
        """Return True if device is currently enabled."""
        return dev in self._devices

    def list(self):
        """Return a snapshot of all enabled devices."""
        return set(self._devices)
