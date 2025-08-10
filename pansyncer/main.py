"""
pansyncer main.py
Syncronizes frequencies between FlRig (using rigctld) and GQRX.
Supports Direct Mode (Bidirectional) or iFreq Mode (one-way, with offset)
Keyboard, Mouse or External VFO-Knob can be used to change frequency
"""

import time
import argparse
from argparse import RawTextHelpFormatter
import sys
import tty
import termios
import atexit

from pansyncer.config import Config
from pansyncer.device_register import DeviceRegister
from pansyncer.device_handler import DeviceHandler
from pansyncer.step import StepController
from pansyncer.display import Display
from pansyncer.sync import SyncManager
from pansyncer.logger import Logger

VERSION = '0.4.1'

class PanSyncer:
    """ PanSyncer Application Class"""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.devices = DeviceRegister(self.cfg)                                         # Register devices

        if not {'rig', 'gqrx'} & self.devices.list():                                   # Must have at least one radio
            print("[ERROR] You must specify at least one of --devices f|g")
            sys.exit(1)

        self.is_tty = sys.stdin.isatty() and not self.cfg.main.daemon                   # Check terminal

        if self.cfg.main.daemon:                                                        # Display setup
            self.display = None
        else:
            self.display = Display(self.cfg,
                                   self.devices,
                                   is_tty=self.is_tty)
            atexit.register(self.display.cleanup)

        self.logger = Logger(name=__name__,                                             # User Interface Logger
                             display=self.display,
                             level=self.cfg.main.log_level,
                             logfile_path=self.cfg.main.logfile_path)
        self.devices.logger = self.logger
        atexit.register(self.logger.close)

        if self.cfg.main.ifreq is not None:                                             # Mode setup
            if self.display:
                self.display.set_mode(" iFreq")
                self.display.set_ifreq(self.cfg.main.ifreq)
        else:
            if self.display: self.display.set_mode("Direct")

        self.step = StepController()                                                    # Step setup

        self.sync = SyncManager(self.cfg,                                               # Sync manager
                                self.devices,
                                self.step,
                                display=self.display)
        atexit.register(self.sync.shutdown)

        self.device_handler = DeviceHandler(                                            # Device handler
            cfg = self.cfg,
            is_tty = self.is_tty,
            devices = self.devices,
            logger = self.logger,
            sync = self.sync,
            step = self.step,
            display = self.display,
            keyboard = None)
        atexit.register(self.device_handler.cleanup)

        self.old_term = None                                                           # Setup Terminal
        self._setup_terminal()
        if self.is_tty:
            self.logger.log("\033[1mWelcome to PanSyncer, press \033[96m?\033[0;1m for help.\033[0m", "INFO")

    def main_loop(self):                                                               ##### MAIN LOOP #####
        """Main loop, handling device input, display, and sync."""
        try:
            while True:
                now = time.monotonic()
                if self.device_handler.tick(now):
                    if self.display:
                        self.display.log("[QUIT] shutting down...")
                        self.display.draw(now)
                        break
                self.sync.tick(now)
                if self.display: self.display.draw(now)
        except (KeyboardInterrupt, InterruptedError, EOFError):
            pass

    def cleanup(self):
        """Shut down sync manager and restore terminal settings."""
        try:
            self.device_handler.cleanup()
        except Exception as e:
            self.logger.log(f"device_handler shutdown error: {e}", "ERROR")
        try:
            self.sync.shutdown()
        except Exception as e:
            self.logger.log(f"sync shutdown error: {e}", "ERROR")
        if self.is_tty:
            try:
                sys.stdout.write("\033[?1004l")                                             # disable focus in/out evs
                sys.stdout.flush()
            except Exception:
                pass
            try:
                if self.display:
                    self.display.cleanup()
            except Exception:
                pass
            try:
                self.logger.close()
            except Exception:
                pass
            if self.old_term is not None:                                                   # reset terminal
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self.old_term)

    def _setup_terminal(self):                                                              # Setup terminal
        """Enable raw (cbreak) mode on stdin if running in a TTY."""
        if self.is_tty:
            fd = sys.stdin.fileno()
            self.old_term = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            sys.stdout.write("\033[?1004h") # enable focus in/out events
            sys.stdout.flush()
        else:
            self.cfg.main.daemon= True

    @staticmethod
    def parse_args():
        """Parse and return the application’s command‐line arguments."""
        parser = argparse.ArgumentParser(
            formatter_class=RawTextHelpFormatter,
            description=f"PanSyncer {VERSION} – Sync your Rig and Gqrx. Tune via keyboard, mouse, or external VFO knob.")
        parser.add_argument("-d", "--devices", nargs="+",
            choices=["r", "g", "k", "m", "rig", "gqrx", "knob", "mouse"],
            help="Devices to enable: r=rig, g=gqrx, k=knob, m=mouse")
        parser.add_argument("-r", "--rig-port", type=int,
            help="rigctld port (default: 4532)")
        parser.add_argument("-g", "--gqrx-port", type=int,
            help="Gqrx port (default: 7356)")
        parser.add_argument("-f", "--ifreq", type=float,
            help=("IFreq Mode: param offset in MHz e.g. --ifreq 73.095\n"
                  "Changes LO for hardware-coupled pansyncer frequency\n"
                  "If not specified, Direct Mode is used: Bidirectional freq-sync."))
        parser.add_argument("-n", "--no-auto-rig", action="store_true", default=None,
            help="Require rigctld already running; do not auto-start")
        parser.add_argument("-l", "--log", nargs="?", const="pansyncer.log",
            help="Enable frequency logging; optionally specify logfile path")
        parser.add_argument("-s", "--small_display", action="store_true", default=None,
            help="Show minimal display. Display only essential information for small screens.")
        parser.add_argument("-b", "--daemon", action="store_true", default=None,
            help="Disable inputs and graphical display")
        parser.add_argument('-c', '--config-file',
            default='pansyncer.toml',
            help='Path to TOML config file (default: pansyncer.toml)')
        parser.add_argument("-v", "--version", action="version", version=f"PanSyncer v{VERSION}",
            help="Show program version and exit")
        return parser.parse_args()

def main():
    """PanSyncer lifecycle"""
    args = PanSyncer.parse_args()
    cfg = Config.from_args_and_file(args)
    app = PanSyncer(cfg)
    try:
        app.main_loop()
    finally:
        app.cleanup()

if __name__ == "__main__":
    main()
