"""
pansyncer display.py
ANSI terminal UI.
"""
import sys
import time
import threading
from dataclasses import dataclass
from functools import wraps

@dataclass
class DisplayConfig:
    """Default configuration"""
    log_drop_time: float = 5.0
    input_drop_time: float = 1.0
    log_lines: int = 7
    log_lines_small: int = 1
    small_display: bool = False

def synchronized(method):
    """Decorator to lock all calls to instance methods."""
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper

class Display:
    """ User Interface """

    WATCHED = {
        '_rig_freq', '_rig_status',
        '_gqrx_freq', '_gqrx_status',
        '_knob_connected', '_mouse_connected',
        '_keyboard_input', '_mouse_input', '_knob_input',
        '_sync_on', '_step_value', '_logs',
        '_rigctld_connected', '_rig_connected', '_band_name'
    }
    LABELS = {
        'rig': 'Rig',
        'gqrx': 'Gqrx',
        'knob': 'Knob',
        'mouse': 'Mouse',
        'keyboard': 'Keyboard',
    }

    def __init__(self, cfg, devices, is_tty = False):
        super().__setattr__('_redraw', True) # Redraw flag (overwrite __setattr__ to detect changes)
        self._lock = threading.RLock()                     # Thread lock
        self.cfg = cfg
        self.devices = devices
        self._is_tty = is_tty
        self._frame = ""                                   # Computed frame
        self._frame_parts = []                             # List to store the frame-parts
        self._status_col = 12                              # Columns for labels         # CON/DIS
        self._input_col = 17                                                            # UP/DWN/STP
        self._freq_col = 30                                                             # Frequency
        self._mode_col = self._freq_col - 6                                             # iFreq / Direct
        self._first_device_row = 4
        self._header_width = self._mode_col - 1
        self._label_width  = self._status_col - 1
        self._status_width = self._input_col - self._status_col
        self._input_width  = self._freq_col - self._input_col
        self._header = ''.join([
            f"\033[1;1H{' PanSyncer Control':<{self._header_width}}",
            f"\033[2;1H{' Sync':<{self._label_width}}",
            f"\033[3;1H{' Step':<{self._label_width}}"])
        self._header_small = f"\033[1;1H{' Sync':<{self._label_width}}"
        self._unit = " Hz"
        self._rig_freq = None                                                      # radio state
        self._rig_status = "\033[31mDIS\033[0m"
        self._rigctld_connected = False
        self._rig_connected = False
        self._gqrx_freq = None
        self._gqrx_status = "\033[31mDIS\033[0m"
        self._knob_connected = False                                               # peripheral states
        self._mouse_connected = False
        self._keyboard_input = "   "                                               # inputs
        self._mouse_input = "   "
        self._knob_input = "   "
        self._sync_on = False                                                      # sync, step, mode, band
        self._step_value = 100
        self._mode = ""
        self._ifreq = None
        self._band_name = "    "
        self._logs = []                                                            # logs
        self._last_log_end_row = 0
        self._keyboard_ts = 0.0                                                    # timestamps for auto-clear
        self._mouse_ts = 0.0
        self._knob_ts = 0.0
        width = len(self._fmt_hz(0)) + len(self._unit)                             # Precompute blank frequency
        self._blank_freq = ' ' * width
        self._row_map = {}                                                         # layout control
        if self._is_tty:                                 # Set terminal. Alternate buffer, cursor to home, hide cursor
            print("\033[?1049h\033[H\033[?25l", end='')

    def cleanup(self):
        """ restore cursor and return to normal screen """
        if self._is_tty:
            sys.stdout.write("\033[?25h\033[?1049l")
            sys.stdout.flush()

    @synchronized
    def draw(self, now):
        """  Build one frame and print it """
        old_base = (max(self._row_map.values()) + 1) if self._row_map else (       # Remember log base row
            2 if self.cfg.display.small_display else 4)
        new_logs = [                                                               # Check time-based deletions
            (msg, ts)
            for (msg, ts) in self._logs
            if now - ts < self.cfg.display.log_drop_time
        ]
        if new_logs != self._logs:
            self._logs = new_logs

        if now - self._keyboard_ts >= self.cfg.display.input_drop_time and self._keyboard_input.strip():
            self._keyboard_input = "   "
        if now - self._mouse_ts >= self.cfg.display.input_drop_time and self._mouse_input.strip():
            self._mouse_input = "   "
        if now - self._knob_ts >= self.cfg.display.input_drop_time and self._knob_input.strip():
            self._knob_input = "   "

        if not self._redraw:                                                       # Do not draw if nothing has changed
            return
        self._redraw = False

        self._frame_parts.clear()                                                  # start new frame
        self._frame_parts.append("\033[H")                                         # move cursor to home

        small = self.cfg.display.small_display                 # draw header
        self._frame_parts.append(self._header_small if small else self._header)
        first_device_row = 2 if small else 4

        if self.cfg.display.small_display:                     # only radio devices in small_display
            device_rows = [(k, self.LABELS[k]) for k in ('rig', 'gqrx') if self.devices.enabled(k)]
        else:
            device_rows = [(k, v) for (k, v) in self.LABELS.items() if self.devices.enabled(k)]


        old_count = len(self._row_map)                                             # clear if row count changed
        new_count = len(device_rows)
        if new_count != old_count:
            for r in range(first_device_row + min(old_count, new_count),
                           first_device_row + max(old_count, new_count)):
                self._frame_parts.append(f"\033[{r};1H\033[K")
            for r in range(first_device_row, first_device_row + new_count):
                self._frame_parts.append(
                    f"\033[{r};{self._status_col}H{'':{self._status_width}}"
                    f"\033[{r};{self._input_col}H{'':{self._input_width}}")

        self._row_map.clear()                                                      # rebuild row map for device rows
        for row, (dev, label) in enumerate(device_rows, start=first_device_row):
            self._row_map[dev] = row
            self._frame_parts.append(f"\033[{row};1H {label:<{self._label_width - 1}}")

        if not self.cfg.display.small_display: # Mode label
            self._frame_parts.append(f"\033[1;{self._mode_col}H\033[96m{self._mode}\033[0m")

        if not self.cfg.display.small_display:
            sync_status_row = 2
            step_freq_row = 3
            if self._ifreq is not None:
                self._draw_freq(2, self._ifreq)                               # iFreq
        else:
            sync_status_row = 1
            step_freq_row = 1

        self._draw_freq(step_freq_row, self._step_value)                           # Step frequency

        status = "ON " if self._sync_on else "OFF"                                 # Sync status
        color = "32" if self._sync_on else "31"
        self._frame_parts.append(
            f"\033[{sync_status_row};{self._status_col}H\033[{color}m{status:<{self._status_width}}\033[0m")

        if self.devices.enabled('rig'):                                           # Rig
            r = self._row_map['rig']
            self._frame_parts.append(f"\033[{r};{self._status_col}H{self._rig_status}")
            self._draw_freq(r, self._rig_freq)

        if self.devices.enabled('gqrx'):                                          # Gqrx
            r = self._row_map['gqrx']
            self._frame_parts.append(f"\033[{r};{self._status_col}H{self._gqrx_status}")
            self._draw_freq(r, self._gqrx_freq)

        if not self.cfg.display.small_display:
            if self.devices.enabled('knob'):                                       # Knob
                r = self._row_map['knob']
                color = "32" if self._knob_connected else "31"
                self._frame_parts.append(f"\033[{r};{self._status_col}H\033[{color}m{'CON' if self._knob_connected else 'DIS'}\033[0m")
                self._frame_parts.append(f"\033[{r};{self._input_col}H{self._knob_input:<3}")

            if self.devices.enabled('mouse'):                                      # Mouse
                r = self._row_map['mouse']
                color = "32" if self._mouse_connected else "31"
                self._frame_parts.append(f"\033[{r};{self._status_col}H\033[{color}m{'CON' if self._mouse_connected else 'DIS'}\033[0m")
                self._frame_parts.append(f"\033[{r};{self._input_col}H{self._mouse_input:<3}")

            r = self._row_map['keyboard']                                          # Keyboard (always enabled)
            self._frame_parts.append(f"\033[{r};{self._status_col}H{'':<{self._status_width}}")
            self._frame_parts.append(f"\033[{r};{self._input_col}H{self._keyboard_input:<3}")
            col = self._freq_col - len(self._band_name)                            # Band name
            self._frame_parts.append(f"\033[{r};{col}H\033[1;96m{self._band_name}\033[0m")

        base_row = max(self._row_map.values()) + 1 if self._row_map else first_device_row # Logs
                                                                                   # One line log in small_display
        display_log_lines = self.cfg.display.log_lines_small if self.cfg.display.small_display else self.cfg.display.log_lines
        if base_row > old_base:                                                    # Clear on log pushdown (device add)
            for clear_row in range(old_base, base_row):
                if clear_row not in self._row_map.values():
                    self._frame_parts.append(f"\033[{clear_row};1H\033[K")
        count = len(self._logs)
        for idx in range(display_log_lines):
            row = base_row + idx
            if idx < count:
                if self.cfg.display.small_display:
                    line = self._logs[idx][0].splitlines()[0]
                else:
                    line = self._logs[count - 1 - idx][0].splitlines()[0]
                self._frame_parts.append(f"\033[{row};1H\033[K{line}")
            else:
                self._frame_parts.append(f"\033[{row};1H\033[K")

        log_end_row = base_row + display_log_lines - 1                            # If logs moved up, because of
        if self._last_log_end_row > log_end_row:                                  # device removal: Clear last line
            for row in range(log_end_row + 1, self._last_log_end_row + 1):
                self._frame_parts.append(f"\033[{row};1H\033[K")
        self._last_log_end_row = log_end_row

        self._frame = "".join(self._frame_parts)                            # Put frame together and write it to screen
        sys.stdout.write(self._frame)
        sys.stdout.flush()

    @synchronized
    def set_mode(self, mode: str):
        """Set the mode label (e.g., 'iFreq' or 'Direct')."""
        self._mode = mode

    @synchronized
    def set_ifreq(self, freq: int):
        """Set the intermediate frequency (Hz) to display."""
        self._ifreq = int(freq * 1_000_000)

    @synchronized
    def set_sync_mode(self, on: bool):
        """Set Sync mode On/Off"""
        self._sync_on = on

    @synchronized
    def set_step_value(self, step):
        """Set frequency increment"""
        self._step_value = step

    @synchronized
    def set_rig_con(self, rig_connected):
        """Set rig connection status (CON in green)"""
        self._rig_connected = rig_connected
        self.set_rig(self._rig_freq, self._rigctld_connected)

    @synchronized
    def set_rig(self, freq, rigctl_connected):
        """Set rig frequency and status"""
        self._rigctld_connected = rigctl_connected
        self._rig_freq = freq

        if self._rigctld_connected and self._rig_connected:                       # RIG connected to rigctl
            self._rig_status = "\033[32mCON\033[0m"
        elif self._rigctld_connected:                                             # rigctl connected, no RIG
            self._rig_status = "CON"
        else:                                                                     # rigctl disconnected
            self._rig_status = "\033[31mDIS\033[0m"

    @synchronized
    def set_gqrx(self, freq, connected):
        """Set Gqrx frequency and status"""
        self._gqrx_freq = freq
        self._gqrx_status = "\033[32mCON\033[0m" if connected else "\033[31mDIS\033[0m"

    @synchronized
    def set_knob(self, connected=True):
        """Set Knob status"""
        self._knob_connected = connected

    @synchronized
    def set_mouse(self, connected: bool):
        """Set Mouse status"""
        self._mouse_connected = connected

    @synchronized
    def set_keyboard_input(self, text: str):
        """Set keyboard input indicator and timestamp for deletion"""
        self._keyboard_input = text[:3]
        self._keyboard_ts = time.monotonic()

    @synchronized
    def set_band_name(self, name: str):
        """Set the band label"""
        self._band_name = (name or "").rjust(4)[:4]

    @synchronized
    def set_mouse_input(self, text: str):
        """Set mouse input indicator and timestamp for deletion"""
        self._mouse_input = text[:3]
        self._mouse_ts = time.monotonic()

    @synchronized
    def set_knob_input(self, text: str):
        """Set knob input indicator and timestamp for deletion"""
        self._knob_input = text[:3]
        self._knob_ts = time.monotonic()

    @synchronized
    def toggle_small_display(self):
        """Toggle compact UI and trigger a repaint."""
        self.cfg.display.small_display = not self.cfg.display.small_display
        sys.stdout.write("\033[2J\033[H")                                        # Clear screen and redraw on toggle
        sys.stdout.flush()
        super().__setattr__('_redraw', True)

    @synchronized
    def log(self, text: str):
        """ log display """
        try:
            logline = text.split('\n', 1)[0]                         # only use the first line
            self._logs.insert(0, (logline, time.monotonic()))      # push newest message to front
                                                                                  # small display log line limit
            limit = self.cfg.display.log_lines_small if self.cfg.display.small_display else self.cfg.display.log_lines
            if len(self._logs) > limit:                                           # keep only the most recent
                self._logs.pop()
            super().__setattr__('_redraw', True)
        except (AttributeError, TypeError) as e:
            print(f"PanSyncer Display log error  {e}", file=sys.stderr)
            return

    def _draw_freq(self, row, freq = None, style = ""):
        """ Draw a frequency string with unit """
        if freq is None:
            start_col = self._freq_col - len(self._blank_freq)
            self._frame_parts.append(f"\033[{row};{start_col}H{self._blank_freq}")
        else:
            freq_str = self._fmt_hz(freq) + self._unit
            start_col = self._freq_col - len(freq_str)
            self._frame_parts.append(f"\033[{row};{start_col}H{style}{freq_str}\033[0m")

    @staticmethod
    def _fmt_hz(freq):
        """ Frequency format """
        if freq is None:
            return ' ' * 10
        s = f"{int(freq):,}".replace(",", ".")                        # Insert dots every three digits
        return s.rjust(10)                                                        # Right-justify to field width 10

    def __setattr__(self, name, value):
        """ Sets the redraw flag if one of the watched attributes change"""
        if name == '_lock':
            super().__setattr__(name, value)
            return
        with self._lock:
            if name == '_redraw':
                super().__setattr__(name, value)
                return
            if name in self.WATCHED:
                old = getattr(self, name, None)
                if value != old:
                    super().__setattr__('_redraw', True)
            super().__setattr__(name, value)
