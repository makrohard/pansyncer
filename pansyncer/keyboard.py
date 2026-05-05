"""
pansyncer keyboard.py
Uses stdin. First parses escape commands for focus and arrow keys,
then processes a single character.
"""
import sys
import os
from pansyncer.utils import beep

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
        self._paste_mode = False
        self._input_buf = bytearray()

    def get_fd(self):
        """Return file descriptor."""
        return self._fd

    @staticmethod
    def _csi_len(data, start):
        """Return complete CSI sequence length, or 0 if incomplete."""
        for pos in range(start + 2, len(data)):
            if 0x40 <= data[pos] <= 0x7e:
                return pos - start + 1
        return 0

    def read_stdin(self, fd, now):
        """ Read raw data from stdin do detect Escape-Sequences """
        chunk = os.read(fd, 32)                                                  # read up to 32 bytes
        if not chunk:
            return True
        self._input_buf.extend(chunk)
        i = 0
        data = self._input_buf
        l = len(data)
        while i < l:
            remaining = l - i
            if data[i] == 0x1b:
                if remaining < 6 and (                                                 # keep incomplete paste sequence
                        b'\x1b[200~'.startswith(bytes(data[i:])) or
                        b'\x1b[201~'.startswith(bytes(data[i:]))):
                    break

                if data.startswith(b'\x1b[200~', i):                           # bracketed paste start
                    self._paste_mode = True
                    i += 6
                    continue
                if data.startswith(b'\x1b[201~', i):                           # bracketed paste end
                    self._paste_mode = False
                    i += 6
                    continue
                if remaining < 3:                                                     # keep incomplete ESC sequence
                    break

                if data[i + 1] == ord('['):                                           # look for CSI sequences
                    seq_len = self._csi_len(data, i)
                    if seq_len == 0:
                        break                                                         # keep incomplete CSI sequence

                    code = data[i + seq_len - 1]                                      # final byte
                    if code == ord('I'):
                        self.focused = True                                           # Focus IN
                        self.logger.log("Window got focus", "DEBUG")
                    elif code == ord('O'):
                        self.focused = False                                          # Focus Out
                        self.logger.log("Window Lost focus", "DEBUG")
                    elif code == ord('A'):                                            # Up arrow
                        # Some terminals bind mouse-wheel to up/down, so we do a time-based debounce on arrow keys.
                        if not (self.mouse and (
                                now - getattr(self.mouse, 'last_scroll_time', 0) < (self.interval * 4))):
                            if self.handle_events('+') == 'quit':
                                del data[:i + seq_len]
                                return True
                    elif code == ord('B'):                                            # Down arrow
                        if not (self.mouse and (
                                now - getattr(self.mouse, 'last_scroll_time', 0) < (self.interval * 4))):
                            if self.handle_events('-') == 'quit':
                                del data[:i + seq_len]
                                return True

                    i += seq_len                                                      # consume complete CSI sequence
                    continue

            if self._paste_mode:                                                      # ignore pasted text
                i += 1
                continue

            ch = chr(data[i])                                                         # normal byte – process as character
            if self.handle_events(ch) == "quit":
                del data[:i + 1]
                return True
            i += 1

        del data[:i]
        return False

    def handle_events(self, key: str = None):
        """Parse a key press and execute the corresponding action."""

        if key is None:
            return
                                                                                        # Help
        elif key == '?':
            self.logger.log("Change Frequency :  + / -, arrow keys, mouse or external VFO Knob", "INFO")
            self.logger.log("Sync On / Off    :  1 / 0", "INFO")
            self.logger.log("Change Step      :  Spacebar, middle mouse button or knob click", "INFO")
            self.logger.log("Toggle devices   :  r = Rig,  g = Gqrx, m = Mouse, k = VFO Knob", "INFO")
            self.logger.log("Change Band      :  w = Up,  s = Down", "INFO")
            self.logger.log("Toggle display   :  d", "INFO")
            self.logger.log("Quit             :  q ", "INFO")
                                                                                       # Switch sync ON
        elif key == '1':

            rig = self.sync.radio['rig']
            gqrx = self.sync.radio['gqrx']
            rig_ok = (
                    rig['sock'] is not None
                    and rig['connected']
                    and self.devices.enabled('rig')
            )
            gqrx_ok = (
                    gqrx['sock'] is not None
                    and gqrx['connected']
                    and self.devices.enabled('gqrx')
            )
            if rig_ok and gqrx_ok:
                self.sync.set_sync_mode(True)
                if self.display: self.display.set_sync_mode(True)
                self.logger.log('Sync ON', 'INFO')
            else:
                self.sync.set_sync_mode(False)
                if self.display:
                    self.display.set_sync_mode(False)
                self.logger.log('Cannot enable sync – both Rig and Gqrx must be connected.', 'ERROR')
                beep()
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
            if self.display: self.display.set_keyboard_input('GQR')
            self.logger.log(f"[DEVICE] GQRX {state}", "DEBUG")

                                                                                        # Toggle rig
        elif key.upper() == 'R':
            self.devices.toggle('rig')
            state = 'ENABLED' if self.devices.enabled('rig') else 'DISABLED'
            if self.display: self.display.set_keyboard_input('RIG')
            self.logger.log(f"[DEVICE] RIG {state}", "DEBUG")

                                                                                        # Toggle Knob
        elif key.upper() == 'K':
            self.devices.toggle('knob')
            state = 'ENABLED' if self.devices.enabled('knob') else 'DISABLED'
            if self.display: self.display.set_keyboard_input('KNB')
            self.logger.log(f"[DEVICE] KNOB {state}", "DEBUG")

                                                                                        # Toggle Mouse
        elif key.upper() == 'M':
            self.devices.toggle('mouse')
            state = 'ENABLED' if self.devices.enabled('mouse') else 'DISABLED'
            if self.display: self.display.set_keyboard_input('MSE')
            self.logger.log(f"[DEVICE] MOUSE {state}", "DEBUG")
                                                                                        # Band up
        elif key.upper() == 'W':
            self.sync.band_step(1)
            if self.display: self.display.set_keyboard_input('BUP')
            self.logger.log("Band up", "INFO")
                                                                                        # Band down
        elif key.upper() == 'S':
            self.sync.band_step(-1)
            if self.display: self.display.set_keyboard_input('BDN')
            self.logger.log("Band down", "INFO")
                                                                                        # Toggle Display
        elif key.upper() == 'D':
            if self.display:
                self.display.toggle_small_display()
                state = 'SMALL' if self.display.cfg.display.small_display else 'FULL'
                if self.display: self.display.set_keyboard_input('DSP')
                self.logger.log(f"[DISPLAY TOGGLE] {state}", "DEBUG")
                                                                                        # Quit command
        elif key.upper() == 'Q':
            if self.display: self.display.set_keyboard_input('EXT')
            return 'quit'

        return None
