"""
pansyncer keyboard.py
Uses stdin. First parses escape commands for focus and arrow keys,
then processes a single character.
"""
import sys
import os

class KeyboardController:
    """ Keyboard event handling via stdin """

    def __init__(self, interval, devices, sync, logger, step, display=None , mouse = None):
        self.interval = interval
        self.devices  = devices
        self.sync     = sync
        self.logger   = logger
        self.step     = step
        self.display  = display
        self.mouse    = mouse
        self._fd      = sys.stdin.fileno()
        self.focused  = True

    def get_fd(self):
        """Return file descriptor."""
        return self._fd

    def read_stdin(self, fd, now):
        """ Read raw data from stdin do detect Escape-Sequences """
        data = os.read(fd, 32)                                                    # read up to 32 bytes
        i = 0
        l = len(data)
        while i < l:
            if data[i] == 0x1b and i+2 < l and data[i+1] == ord('['):                   # look for ESC sequences
                code = data[i+2]
                if code == ord('I'):
                    self.focused = True                                                 # Focus IN
                    self.logger.log("Window got focus", "DEBUG")
                elif code == ord('O'):
                    self.focused = False                                                # Focus Out
                    self.logger.log("Window Lost focus", "DEBUG")
                elif code == ord('A'):                                                  # Up arrow
                    # Some terminals bind mouse-wheel to up/down, so we do a time-based debounce on arrow keys.
                    if not (self.mouse and (
                            now - getattr(self.mouse, 'last_scroll_time', 0) < (self.interval * 4))):
                        if self.handle_events('+') == 'quit':
                            return True
                elif code == ord('B'):                                                  # Down arrow
                    if not (self.mouse and (
                            now - getattr(self.mouse, 'last_scroll_time', 0) < (self.interval * 4))):
                        if self.handle_events('-') == 'quit':
                            return True
                i += 3 # advance past the CSI triplet
            else:
                ch = chr(data[i]) # normal byte – process as character
                if self.handle_events(ch) == "quit":
                    return True
                i += 1

    def handle_events(self, key: str = None):
        """Parse a key press and execute the corresponding action."""

        if key is None:
            return
                                                                                        # Help
        elif key == '?':
            self.logger.log("Change Frequency :  + / -, arrow keys, mouse or external VFO Knob", "INFO")
            self.logger.log("Sync On / Off    :  1 / 0", "INFO")
            self.logger.log("Change Step      :  Spacebar, middle mouse button or knob click", "INFO")
            self.logger.log("Toggle devices   :  r = Rig,  g = Gqrx, m = Mouse k = VFO Knob", "INFO")
            self.logger.log("Quit             :  q ", "INFO")

        # Switch sync ON
        elif key == '1':

            if (self.sync.radio['rig']['sock'] is not None and self.devices.enabled('rig')
            or self.sync.radio['gqrx']['sock'] is not None and self.devices.enabled('gqrx')):
                self.sync.set_sync_mode(True)
                if self.display: self.display.set_sync_mode(True)
                self.logger.log('Sync ON', 'INFO')
            else:
                self.logger.log('Cannot enable sync – both Rig and Gqrx must be connected.', 'ERROR')
            return None
                                                                                        # Switch sync OFF
        if key == '0':
            self.sync.set_sync_mode(False)
            if self.display: self.display.set_sync_mode(False)
            self.logger.log('Sync OFF', 'INFO')
            return None

                                                                                        # Nudge frequency
        if key == '+':
            self.sync.nudge(self.step.get_step())
            if self.display: self.display.set_keyboard_input('UP ')
        elif key == '-':
            self.sync.nudge(-self.step.get_step())
            if self.display: self.display.set_keyboard_input('DWN')

                                                                                        # Cycle step size
        elif key == ' ':
            self.step.next_step()
            if self.display: self.display.set_step_value(self.step.get_step())
            if self.display: self.display.set_keyboard_input('STP')

                                                                                        # Toggle Gqrx
        if key.upper() == 'G':
            self.devices.toggle('gqrx')
            state = 'ENABLED' if self.devices.enabled('gqrx') else 'DISABLED'
            self.logger.log(f"[DEVICE] GQRX {state}", "DEBUG")

                                                                                        # Toggle rig
        elif key.upper() == 'R':
            self.devices.toggle('rig')
            state = 'ENABLED' if self.devices.enabled('rig') else 'DISABLED'
            self.logger.log(f"[DEVICE] RIG {state}", "DEBUG")

                                                                                        # Toggle Knob
        elif key.upper() == 'K':
            self.devices.toggle('knob')
            state = 'ENABLED' if self.devices.enabled('knob') else 'DISABLED'
            self.logger.log(f"[DEVICE] KNOB {state}", "DEBUG")

                                                                                        # Toggle Mouse
        elif key.upper() == 'M':
            self.devices.toggle('mouse')
            state = 'ENABLED' if self.devices.enabled('mouse') else 'DISABLED'
            self.logger.log(f"[DEVICE] MOUSE {state}", "DEBUG")
                                                                                        # Quit command
        elif key.upper() == 'Q':
            return 'quit'

        return None
