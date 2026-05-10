"""
pansyncer device_handler.py
Handles input devices: Keyboard (stdin), Mouse or External VFO-Knob
as well as radio devices: Rig (hamlib rigctld) and GQRX.
Does periodic connection checks, and input event polling.
"""

import time
import select
import io
import threading
import errno

from pansyncer.rigcheck import RigChecker
from pansyncer.keyboard import KeyboardController
from pansyncer.mouse import MouseState
from pansyncer.knob import KnobController
from pansyncer.reconnect_scheduler import ReconnectScheduler


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
        self._lifecycle_lock = threading.RLock()
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

        if self.devices.enabled('rig'):
            self._on_rig_added('rig')

        if self.devices.enabled('knob'):
            self._on_knob_added('knob')

        if self.devices.enabled('mouse'):
            self._on_mouse_added('mouse')

                                                                                        ##### PUBLIC API
    def tick(self, now):
        """Run periodic tasks, then poll FDs & dispatch events.
        Returns True if main loop should exit."""
        self.scheduler.tick()
        return self._poll_inputs(now)

    def cleanup(self):
        """Release resources & stop background activities."""
        try:
            self.scheduler.shutdown(wait=True)
        except Exception as e:
            self.logger.log(f'scheduler shutdown error: {e}', 'ERROR')

        with self._lifecycle_lock:
            if self._rigchk:
                try:
                    self._rigchk.cleanup()
                except Exception as e:
                    self.logger.log(f'rigchk cleanup error: {e}', 'ERROR')
                finally:
                    self._rigchk = None

            if self._knob:
                try:
                    self._knob.disconnect()
                except Exception as e:
                    self.logger.log(f'knob disconnect error: {e}', 'ERROR')
                finally:
                    self._knob = None

            if self._mouse:
                try:
                    self._mouse.disconnect()
                except Exception as e:
                    self.logger.log(f'mouse disconnect error: {e}', 'ERROR')
                finally:
                    self._mouse = None
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

    def _input_controller_snapshot(self):
        """Return the currently active input controllers for one poll cycle."""
        with self._lifecycle_lock:
            knob = self._knob if self.devices.enabled('knob') else None
            mouse = self._mouse if self.devices.enabled('mouse') else None
        return knob, mouse

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

        knob, mouse = self._input_controller_snapshot()

        kfd = None                                                                      # Knob FD
        if knob:
            try:
                kfd = knob.fd()
                if kfd is not None:
                    fds.append(kfd)
            except (AttributeError, OSError, ValueError) as e:
                self.logger.log(f'knob fd error: {e}', 'ERROR')
                self._refresh_knob_connected('fd error', controller=knob)
                kfd = None

        mouse_fds = []                                                                  # Mouse FDs
        if mouse:
            try:
                mouse_fds = mouse.get_fds()
                fds.extend(mouse_fds)
            except (AttributeError, OSError, ValueError) as e:
                self.logger.log(f'mouse fds error: {e}', 'ERROR')
                self._refresh_mouse_connected('fd error', controller=mouse)
                mouse_fds = []

        fds = list(dict.fromkeys(fds))                                                  # De-duplicate FDs
        if not fds:                                                                     # Nothing to poll
            time.sleep(self.interval)
            return False

        try:                                                                            # *** CALL SELECT ***
            rlist, _, _ = select.select(fds, [], [], self.interval)
        except (KeyboardInterrupt, InterruptedError):                                   # SIGINT
            raise
        except ValueError as e:
            self.logger.log(f'select fd error: {e}', 'ERROR')
            self._handle_bad_fds(stdin_fd, kfd, mouse_fds, knob=knob, mouse=mouse)
            return False
        except OSError as e:
            self.logger.log(f'select error: {e}', 'ERROR')

            if getattr(e, "errno", None) == errno.EBADF:
                self._handle_bad_fds(stdin_fd, kfd, mouse_fds, knob=knob, mouse=mouse)

            return False

        for fd in rlist:                                                               # Dispatch events
            if stdin_fd is not None and fd == stdin_fd and self.keyboard:
                if self.keyboard.read_stdin(fd, now):
                    return True
            elif kfd is not None and fd == kfd and knob:
                try:
                    knob.handle_events(self.sync, self.step)
                except (OSError, ValueError) as e:
                    self.logger.log(f'knob handler error: {e}', 'ERROR')
                    self._refresh_knob_connected('handler error', controller=knob)
            elif mouse and fd in mouse_fds and (self.keyboard.focused if self.keyboard else True):
                try:
                    mouse.handle_event(fd, self.sync, self.step, now)
                except (OSError, ValueError) as e:
                    self.logger.log(f'mouse handler error: {e}', 'ERROR')
                    self._refresh_mouse_connected('handler error', controller=mouse)
        return False

    def _ensure_knob_connected(self):
        """Reconnect knob only while it is still enabled and registered."""
        with self._lifecycle_lock:
            if not self.devices.enabled('knob') or self._knob is None:
                return False
            return self._knob.ensure_connected()

    def _ensure_mouse_connected(self):
        """Reconnect mouse only while it is still enabled and registered."""
        with self._lifecycle_lock:
            if not self.devices.enabled('mouse') or self._mouse is None:
                return False
            return self._mouse.ensure_connected()

    def _refresh_mouse_connected(self, reason, controller=None):
        """Refresh mouse hardware state."""
        with self._lifecycle_lock:
            if not self.devices.enabled('mouse') or self._mouse is None:
                return False
            if controller is not None and self._mouse is not controller:
                return False
            try:
                return self._mouse.refresh()
            except (AttributeError, OSError, IOError, ValueError, RuntimeError) as e:
                self.logger.log(f'mouse refresh after {reason}: {e}', 'ERROR')
                return False

    def _refresh_knob_connected(self, reason, controller=None):
        """Reset knob hardware state."""
        with self._lifecycle_lock:
            if not self.devices.enabled('knob') or self._knob is None:
                return False
            if controller is not None and self._knob is not controller:
                return False
            try:
                self._knob.disconnect()
                return False
            except (AttributeError, OSError, IOError, ValueError, RuntimeError) as e:
                self.logger.log(f'knob refresh after {reason}: {e}', 'ERROR')
                return False

    @staticmethod
    def _fd_is_valid(fd):
        """Return False if fd is invalid."""
        if fd is None:
            return False

        try:
            if fd < 0:
                return False
            select.select([fd], [], [], 0)
            return True
        except ValueError:
            return False
        except OSError as e:
            return getattr(e, "errno", None) != errno.EBADF

    def _handle_bad_fds(self, stdin_fd, kfd, mouse_fds, knob=None, mouse=None):
        """Handle EBADF by checking each FD."""
        if stdin_fd is not None and not self._fd_is_valid(stdin_fd):
            self.logger.log('stdin fd became invalid', 'ERROR')

        if (
            kfd is not None
            and self.devices.enabled('knob')
            and not self._fd_is_valid(kfd)
        ):
            self._refresh_knob_connected('bad fd', controller=knob)

        if mouse_fds and self.devices.enabled('mouse'):
            bad_mouse_fds = [
                fd for fd in mouse_fds
                if not self._fd_is_valid(fd)
            ]
            if bad_mouse_fds:
                self._refresh_mouse_connected('bad fd', controller=mouse)

    def _check_rig_connected(self):
        """Check rig only while it is still enabled and registered."""
        with self._lifecycle_lock:
            if not self.devices.enabled('rig') or self._rigchk is None:
                return False
            return self._rigchk.check_rig()

    @property                                                                         ##### Properties
    def knob(self):
        with self._lifecycle_lock:
            if self._knob is None and self.devices.enabled('knob'):
                self._knob = KnobController(self.cfg, self.logger, self.display)
                try:
                    self._knob.ensure_connected()
                    self.scheduler.register(self._ensure_knob_connected, tag='knob', backoff=True)
                except (OSError, IOError, TimeoutError) as e:
                    self._knob = None
                    self.logger.log(f'Knob connect error: {e}', 'ERROR')
            return self._knob

    @property
    def mouse(self):
        with self._lifecycle_lock:
            if self._mouse is None and self.devices.enabled('mouse'):
                self._mouse = MouseState(time.monotonic(), self.logger, self.display)
                try:
                    self._mouse.ensure_connected()
                    self.scheduler.register(self._ensure_mouse_connected, tag='mouse', backoff=True)
                except (OSError, IOError, TimeoutError) as e:
                    self._mouse = None
                    self.logger.log(f'Mouse connect error: {e}', 'ERROR')
            return self._mouse

    @property
    def rigchk(self):
        with self._lifecycle_lock:
            if self._rigchk is None and self.devices.enabled('rig'):
                self._rigchk = RigChecker(
                    self.cfg,
                    port=self.cfg.sync.rig_port,
                    display=self.display,
                    auto_start=not self.cfg.main.no_auto_rig
                )
                if self.display:
                    self.display.rigchk = self._rigchk
                try:
                    self._rigchk.check_rig()
                    self.scheduler.register(self._check_rig_connected, tag='rig', backoff=True)
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
        if dev == 'knob':
            with self._lifecycle_lock:
                self.scheduler.unregister_tag('knob')
                if self._knob:
                    try:
                        self._knob.disconnect()
                    except (OSError, IOError) as e:
                        self.logger.log(f'knob disconnect error: {e}', 'ERROR')
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
        if dev == 'mouse':
            with self._lifecycle_lock:
                self.scheduler.unregister_tag('mouse')
                if self._mouse:
                    try:
                        self._mouse.disconnect()
                    except (OSError, IOError) as e:
                        self.logger.log(f'mouse disconnect error: {e}', 'ERROR')
                    if self.keyboard:
                        self.keyboard.mouse = None
                    self._mouse = None
                    self.logger.log('Mouse removed', 'DEBUG')

    def _on_rig_added(self, dev):
        if dev == 'rig':
            _ = self.rigchk
            self.logger.log('Rig added', 'DEBUG')

    def _on_rig_removed(self, dev):
        if dev == 'rig':
            with self._lifecycle_lock:
                self.scheduler.unregister_tag('rig')
                try:
                    self.sync.shutdown(role='rig')
                except (OSError, IOError, RuntimeError) as e:
                    self.logger.log(f'sync rig shutdown error: {e}', 'ERROR')
                if self._rigchk:
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