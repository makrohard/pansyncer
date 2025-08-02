"""
pansyncer config.py
Central configuration loader that uses per-module config classes
"""

import tomllib
from dataclasses import dataclass
from typing import Optional

from pansyncer.sync import SyncConfig
from pansyncer.device_register import DeviceRegisterConfig
from pansyncer.display import DisplayConfig
from pansyncer.knob import KnobConfig
from pansyncer.rigcheck import RigCheckConfig
from pansyncer.reconnect_scheduler import SchedulerConfig

@dataclass
class MainConfig:
    daemon: bool = False
    ifreq: Optional[float] = None
    no_auto_rig: bool = False
    interval: float = 0.1
    config_file: str = "pansyncer.toml"
    log_level: str = "INFO"
    logfile_path: Optional[str] = None

class Config:
    """ Read dataclasses from modules and provide cfg"""
    def __init__(self,
                 main=None,
                 sync=None,
                 devices=None,
                 display=None,
                 knob=None,
                 rigcheck=None,
                 reconnect_scheduler=None):
        self.main = main or MainConfig()
        self.sync = sync or SyncConfig()
        self.devices = devices or DeviceRegisterConfig()
        self.display = display or DisplayConfig()
        self.knobs = knob or [KnobConfig()]
        self.rigcheck = rigcheck or RigCheckConfig()
        self.reconnect_scheduler = reconnect_scheduler or SchedulerConfig()

    @classmethod
    def from_args_and_file(cls, args):
                                                                                        # instantiate defaults
        cfg = cls()
                                                                                        # load toml file
        try:
            path = args.config_file or "pansyncer.toml"
            with open(path, 'rb') as f:
                data = tomllib.load(f)
        except FileNotFoundError:
            data = {} # FIXME log config file not found error
                                                                                        # overlay file data
        for section_name in ('main', 'sync', 'devices', 'display', 'rigcheck', 'reconnect_scheduler'):
            section_data = data.get(section_name, {})
            if isinstance(section_data, dict):
                section_obj = getattr(cfg, section_name)
                for key, val in section_data.items():
                    if hasattr(section_obj, key):
                        setattr(section_obj, key, val)

        cfg.knobs = []
        for entry in data.get('knobs', []):                                             # Read knobs definition
            cfg.knobs.append(KnobConfig(**entry))
                                                                                        # overlay CLI args
        for key, val in vars(args).items():
            if val is None:
                continue
            if hasattr(cfg.main, key):
                setattr(cfg.main, key, val)
            elif hasattr(cfg.sync, key):
                setattr(cfg.sync, key, val)
                                                                                        # overlay devices from args
        if args.devices is not None:
            map_ = DeviceRegisterConfig().device_map
            cfg.devices.enabled = [map_.get(d, d) for d in args.devices]

        return cfg
