"""
pansyncer config.py
Central configuration loader that uses per-module config classes
"""

import sys
import tomllib
from dataclasses import dataclass
from typing import Optional

from pansyncer.sync import SyncConfig
from pansyncer.device_register import DeviceRegisterConfig
from pansyncer.display import DisplayConfig
from pansyncer.knob import KnobConfig
from pansyncer.rigcheck import RigCheckConfig
from pansyncer.reconnect_scheduler import SchedulerConfig
from pansyncer.evdev_hotplug import InputHotplugConfig
from pansyncer.bands import Band, DEFAULT_BANDS, normalize_bands

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
                 reconnect_scheduler=None,
                 input_hotplug=None):
        self.main = main or MainConfig()
        self.sync = sync or SyncConfig()
        self.devices = devices or DeviceRegisterConfig()
        self.display = display or DisplayConfig()
        self.knobs = knob or [KnobConfig()]
        self.rigcheck = rigcheck or RigCheckConfig()
        self.reconnect_scheduler = reconnect_scheduler or SchedulerConfig()
        self.input_hotplug = input_hotplug or InputHotplugConfig()
        self.bands = list(DEFAULT_BANDS)

    @staticmethod
    def _config_error(message, exc=None):
        print(f"[CONFIG ERROR] {message}", file=sys.stderr)
        print(
            "[CONFIG ERROR] You may want to repair that file or delete it and use defaults.",
            file=sys.stderr,
        )
        if exc is not None:
            raise SystemExit(2) from exc
        raise SystemExit(2)

    @classmethod
    def _load_bands(cls, data):
        tbl = data.get("bands") or {}
        if not isinstance(tbl, dict):
            cls._config_error("[bands] must be a TOML table")
        region = tbl.get("region")
        entries = tbl.get(region)
        if not isinstance(entries, list):
            return normalize_bands(DEFAULT_BANDS)
        custom_bands = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                cls._config_error(f"Invalid band entry #{index}: expected table/object")
            try:
                band = Band(name=entry["name"],
                            start=entry["start"],
                            goto=entry.get("goto"),
                            end=entry["end"],)
            except KeyError as e:
                cls._config_error(f"Invalid band entry #{index}: missing field {e}", e)
            custom_bands.append(band)
        try:
            return normalize_bands(custom_bands)
        except ValueError as e:
            cls._config_error(f"Invalid band configuration: {e}", e)

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
            data = {}                                                                   # config is missing, use defaults

        except tomllib.TOMLDecodeError as e:
            cls._config_error(f"Invalid TOML FILE {path}: {e}", e)             # config is invalid, exit with error
            raise SystemExit(2) from e

                                                                                        # overlay file data
        for section_name in ('main', 'sync', 'devices','display','rigcheck', 'reconnect_scheduler','input_hotplug',):
            section_data = data.get(section_name, {})
            if isinstance(section_data, dict):
                section_obj = getattr(cfg, section_name)
                for key, val in section_data.items():
                    if hasattr(section_obj, key):
                        setattr(section_obj, key, val)

                                                                                        # Read knobs definition
        knob_entries = data.get("knobs", [])
        if not isinstance(knob_entries, list):
            cls._config_error("[[knobs]] must be a TOML array of tables")

        cfg.knobs = []
        for index, entry in enumerate(knob_entries):
            if not isinstance(entry, dict):
                cls._config_error(f"Invalid knob entry #{index}: expected table/object")
            try:
                cfg.knobs.append(KnobConfig(**entry))
            except TypeError as e:
                cls._config_error(f"Invalid knob entry #{index}: {e}", e)

        if not cfg.knobs:
            cfg.knobs = [KnobConfig()]

        cfg.bands = cls._load_bands(data)                                               # Read bands
                                                                                        # overlay CLI args
        for key, val in vars(args).items():
            if val is None:
                continue
            if hasattr(cfg.main, key):
                setattr(cfg.main, key, val)
            elif hasattr(cfg.sync, key):
                setattr(cfg.sync, key, val)
            elif hasattr(cfg.display, key):
                setattr(cfg.display, key, val)
                                                                                        # overlay devices from args
        if args.devices is not None:
            map_ = DeviceRegisterConfig().device_map
            cfg.devices.enabled = [map_.get(d, d) for d in args.devices]

        return cfg