"""
pansyncer device_handler.py
Handles input devices: Keyboard (stdin), Mouse or External VFO-Knob
as well as radio devices: Rig (hamlib rigctld) and GQRX.
Does periodic connection checks, and input event polling.
"""

import time
import sys
import select
import io
import atexit

from pansyncer.rigcheck import RigChecker
from pansyncer.keyboard import KeyboardController
from pansyncer.mouse import MouseState
from pansyncer.knob import KnobController
from pansyncer. reconnect_scheduler import ReconnectScheduler


class DeviceHandler:
    """Manage devices, hot-plug hooks, periodic reconnection tasks, and FD polling."""

    def __init__(self, cfg, is_tty, devices, logger, sync, step, display=None, keyboard=None):
        self.cfg = cfg
        self.is_tty = is_tty
        self.devices = devices
        self.logger = logger
        self.sync = sync
        self.step = step
        self.display = display
        self.keyboard = keyboard

        self.interval = self.cfg.main.interval                                          # Main loop throttle
        self._rigchk = None                                                             # Device controller references
        self._knob = None
        self._mouse = None
                                                                                        # Keyboard (stdin)
        if self.keyboard is None and self.devices.enabled('keyboard'):
            self.keyboard = KeyboardController(
                self.interval,
                self.devices,
                self.sync,
                self.logger,
                self.step,
                display=self.display,
                mouse=self._mouse,
            )

        self._register_hooks()                                                          # Register hooks

        self.scheduler = ReconnectScheduler(                                            # Reconnection scheduler
            self.cfg,
            self.logger)
        atexit.register(self.scheduler.shutdown)

        if self.devices.enabled('rig') and not self.cfg.main.no_auto_rig:
            self._on_rig_added('rig')
            if self._rigchk:
                self.scheduler.register(self._rigchk.check_rig, tag='rig', backoff=True)

        if self.devices.enabled('knob'):
            self._on_knob_added('knob')
            if self._knob:
                self.scheduler.register(self._knob.ensure_connected, tag='knob', backoff=True)

        if self.devices.enabled('mouse'):
            self._on_mouse_added('mouse')
            if self._mouse:
                self.scheduler.register(self._mouse.ensure_connected, tag='mouse', backoff=True)

                                                                                        ##### PUBLIC API
    def tick(self, now):
        """Run periodic tasks, then poll FDs & dispatch events.
        Returns True if main loop should exit."""
        self.scheduler.tick()
        return self._poll_inputs(now)

    def cleanup(self):
        """Release resources & stop background activities."""
        if self._rigchk:
            try:
                self._rigchk.cleanup()
            except Exception as e:
                self.logger.log(f'rigchk cleanup error: {e}', 'ERROR')
        if self._knob:
            try:
                self._knob.disconnect()
            except Exception as e:
                self.logger.log(f'knob disconnect error: {e}', 'ERROR')
        if self._mouse:
            try:
                self._mouse.disconnect()
            except Exception as e:
                self.logger.log(f'mouse disconnect error: {e}', 'ERROR')
        try:
            self.scheduler.shutdown(wait=False)
        except Exception as e:
            self.logger.log(f'scheduler shutdown error: {e}', 'ERROR')
                                                                                        ##### INTERNAL

    def _register_hooks(self):                                                          # Register hooks
        self.devices.on_add(self._on_knob_added)
        self.devices.on_remove(self._on_knob_removed)
        self.devices.on_add(self._on_mouse_added)
        self.devices.on_remove(self._on_mouse_removed)
        self.devices.on_add(self._on_rig_added)
        self.devices.on_remove(self._on_rig_removed)
        self.devices.on_add(self._on_gqrx_added)
        self.devices.on_remove(self._on_gqrx_removed)

    def _poll_inputs(self, now):                                                # FD polling and event dispatch
        fds = []
        stdin_fd = None
        if not self.cfg.main.daemon and self.is_tty and self.keyboard:
            try:
                stdin_fd = self.keyboard.get_fd()
                fds.append(stdin_fd)
            except (io.UnsupportedOperation, ValueError) as e:
                self.logger.log(f'stdin fd error: {e}', 'ERROR')
                stdin_fd = None

        kfd = None                                                                      # Knob FD
        if self._knob and self.devices.enabled('knob'):
            try:
                kfd = self._knob.fd()
                if kfd is not None:
                    fds.append(kfd)
            except (AttributeError, OSError) as e:
                self.logger.log(f'knob fd error: {e}', 'ERROR')
                self.devices.remove('knob')
                kfd = None

        mouse_fds = []                                                                  # Mouse FDs
        if self._mouse and self.devices.enabled('mouse'):
            try:
                mouse_fds = self._mouse.get_fds()
                fds.extend(mouse_fds)
            except (AttributeError, OSError) as e:
                self.logger.log(f'mouse fds error: {e}', 'ERROR')
                self.devices.remove('mouse')
                mouse_fds = []
        try:                                                                           # *** CALL SELECT ***
            rlist, _, _ = select.select(fds, [], [], self.interval)
        except (KeyboardInterrupt, InterruptedError):                                  # SIGINT
            raise
        except OSError as e:
            self.logger.log(f'select error: {e}', 'ERROR')
            return False

        for fd in rlist:                                                               # Dispatch events
            if stdin_fd is not None and fd == stdin_fd and self.keyboard:
                if self.keyboard.read_stdin(fd, now):
                    return True
            elif kfd is not None and fd == kfd and self._knob:
                try:
                    self._knob.handle_events(self.sync, self.step)
                except (OSError, ValueError) as e:
                    self.logger.log(f'knob handler error: {e}', 'ERROR')
            elif self._mouse and fd in mouse_fds and (self.keyboard.focused if self.keyboard else True):
                try:
                    self._mouse.handle_event(fd, self.sync, self.step, now)
                except OSError as e:
                    self.logger.log(f'mouse handler error: {e}', 'ERROR')
        return False

    @property                                                                         ##### Properties
    def knob(self):
        if self._knob is None and self.devices.enabled('knob'):
            self._knob = KnobController(self.cfg, self.logger, self.display)
            atexit.register(self._knob.disconnect)
            try:
                self._knob.ensure_connected()
                self.scheduler.register(self._knob.ensure_connected, tag='knob', backoff=True)
            except (OSError, IOError, TimeoutError) as e:
                self._knob = None
                self.logger.log(f'Knob connect error: {e}', 'ERROR')
        return self._knob

    @property
    def mouse(self):
        if self._mouse is None and self.devices.enabled('mouse'):
            self._mouse = MouseState(time.monotonic(), self.logger, self.display)
            atexit.register(self._mouse.disconnect)
            try:
                self._mouse.ensure_connected()
                self.scheduler.register(self._mouse.ensure_connected, tag='mouse', backoff=True)
            except (OSError, IOError, TimeoutError) as e:
                self._mouse = None
                self.logger.log(f'Mouse connect error: {e}', 'ERROR')
        return self._mouse

    @property
    def rigchk(self):
        if self._rigchk is None and self.devices.enabled('rig'):
            self._rigchk = RigChecker(
                self.cfg,
                port=self.cfg.sync.rig_port,
                display=self.display,
                auto_start=not self.cfg.main.no_auto_rig
            )
            atexit.register(self._rigchk.cleanup)
            if self.display:
                self.display.rigchk = self._rigchk
            try:
                self._rigchk.check_rig()
                self.scheduler.register(self._rigchk.check_rig, tag='rig', backoff=True)
            except (OSError, IOError, TimeoutError) as e:
                self._rigchk = None
                self.logger.log(f'Rigcheck connect error: {e}', 'ERROR')
        return self._rigchk

                                                                                      ##### Event handlers
    def _on_knob_added(self, dev):
        if dev == 'knob':
            _ = self.knob
            self.logger.log('Knob added', 'DEBUG')

    def _on_knob_removed(self, dev):
        if dev == 'knob' and self._knob:
            try:
                self._knob.disconnect()
            except (OSError, IOError) as e:
                self.logger.log(f'knob disconnect error: {e}', 'ERROR')
            self.scheduler.unregister_tag('knob')
            self._knob = None
            self.logger.log('Knob removed', 'DEBUG')
            # Start mouse again - knob presents an unused mouse
            if self.devices.enabled('mouse'):
                self._on_mouse_added('mouse')

    def _on_mouse_added(self, dev):
        if dev == 'mouse':
            _ = self.mouse
            if self.keyboard:
                self.keyboard.mouse = self._mouse
            self.logger.log('Mouse added', 'DEBUG')
            
    def _on_mouse_removed(self, dev):
        if dev == 'mouse' and self._mouse:
            try:
                self._mouse.disconnect()
            except (OSError, IOError) as e:
                self.logger.log(f'mouse disconnect error: {e}', 'ERROR')
            if self.keyboard:
                self.keyboard.mouse = None
            self.scheduler.unregister_tag('mouse')
            self._mouse = None
            self.logger.log('Mouse removed', 'DEBUG')

    def _on_rig_added(self, dev):
        if dev == 'rig':
            _ = self.rigchk
            self.logger.log('Rig added', 'DEBUG')

    def _on_rig_removed(self, dev):
        if dev == 'rig' and self._rigchk:
            self.scheduler.unregister_tag('rig')
            try:
                self.sync.shutdown(role='rig')
            except (OSError, IOError, RuntimeError) as e:
                self.logger.log(f'sync rig shutdown error: {e}', 'ERROR')
            try:
                self._rigchk.cleanup()
            except (OSError, IOError, RuntimeError) as e:
                self.logger.log(f'rigchk shutdown error: {e}', 'ERROR')
            self._rigchk = None
            self.logger.log('Rig removed', 'DEBUG')

    def _on_gqrx_added(self, dev):
        if dev == 'gqrx':
            self.logger.log('GQRX added', 'INFO')
            try:
                self.sync.reconnect_socket(time.monotonic(), 'gqrx')
            except (OSError, IOError, ConnectionError, TimeoutError) as e:
                self.logger.log(f'GQRX reconnect error: {e}', 'ERROR')

    def _on_gqrx_removed(self, dev):
        if dev == 'gqrx':
            self.logger.log('GQRX removed', 'INFO')
            try:
                self.sync.shutdown(role='gqrx')
            except (OSError, IOError, ConnectionError, TimeoutError) as e:
                self.logger.log(f'GQRX shutdown error: {e}', 'ERROR')
