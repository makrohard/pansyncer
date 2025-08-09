"""
pansyncer sync. py
Modes:
        iFreq mode:  RIG  -> GQRX with offset, changes Local Oscillator (LO) frequency
        Direct mode: RIG <-> GQRX, sets FREQUENCY
Handles I/O and frequency syncing. Maintains non-blocking sockets to Rig and Gqrx.
Tracks frequency state of both radios. Follows a strict command / reply logic.
Buffers and limits device input if unable to send immediately.
"""

import socket
import select
import time
import atexit
from dataclasses import dataclass
from typing import Optional
from pansyncer.logger import Logger
from pansyncer.bands import Bands

@dataclass
class SyncConfig:
    """Default configuration"""
                                                                                        # Logger
    log_level:                  str           = "INFO"
    logfile_path:               Optional[str] = None
    freq_log_path:              Optional[str] = None
                                                                                        # Rig settings
    rig_host:                   str           = '127.0.0.1'
    rig_port:                   int           = 4532
    rig_freq_query_interval:    float         = 0.1
    rig_socket_recon_interval:  float         = 3.0
    rig_timeout:                float         = 2.0
                                                                                        # GQRX settings
    gqrx_host:                  str           = '127.0.0.1'
    gqrx_port:                  int           = 7356
    gqrx_freq_query_interval:   float         = 0.1
    gqrx_socket_recon_interval: float         = 3.0
    gqrx_timeout:               float         = 2.0
                                                                                        # Sync & buffering
    wait_before_log_rigfreq:    float         = 5.0
    sync_debounce_time:         float         = 3.0
    nudge_buffer:               int           = 10
    read_buffer_size:           int           = 1024
    max_read_buffer_bytes:      int           = 64 * read_buffer_size

class SyncManager:
    """ SyncManager handles synchronization between Rig and Gqrx clients. """

    def __init__(self,
                 cfg,
                 devices,
                 step,
                 display=None):

        self.cfg = cfg
        self.devices = devices
        self.step = step
        self.display = display
        self.ifreq = self.cfg.main.ifreq
        self._shutdown = False

        self.radio = {
            'rig': {
                'host'                        : self.cfg.sync.rig_host,
                'port'                        : self.cfg.sync.rig_port,
                'sock'                        : None,
                'recon_interval'              : self.cfg.sync.rig_socket_recon_interval,
                'recon_timestamp'             : 0.0,
                'freq_cur'                    : None,
                'freq_prev'                   : 0,
                'freq_sent'                   : None,
                'freq_delta'                  : 0,
                'freq_delta_sent'             : 0,
                'freq_query_interval'         : self.cfg.sync.rig_freq_query_interval,
                'is_busy'                     : None,
                'send_timestamp'              : 0.0,
                'timeout'                     : self.cfg.sync.rig_timeout,
                'recv_buf'                    : bytearray(),
                'command'                     : None,
                'events'                      : []
            },
            'gqrx': {
                'host'                        : self.cfg.sync.gqrx_host,
                'port'                        : self.cfg.sync.gqrx_port,
                'sock'                        : None,
                'recon_interval'              : self.cfg.sync.gqrx_socket_recon_interval,
                'recon_timestamp'             : 0.0,
                'freq_cur'                    : None,
                'freq_prev'                   : 0,
                'freq_sent'                   : None,
                'freq_delta'                  : 0,
                'freq_delta_sent'             : 0,
                'freq_query_interval'         : self.cfg.sync.gqrx_freq_query_interval,
                'is_busy'                     : None,
                'send_timestamp'              : 0.0,
                'timeout'                     : self.cfg.sync.gqrx_timeout,
                'recv_buf'                    : bytearray(),
                'command'                     : None,
                'events'                      : []
            }
        }

        self.sync_on = True  # Sync On/Off
        self._wanted_sync = True
                                                                                        # Display Logger
        self.logger = Logger(name=__name__,
                             display=self.display,
                             level=self.cfg.sync.log_level,
                             logfile_path=self.cfg.sync.logfile_path)
        atexit.register(self.logger.close)
                                                                                        # Frequency Logger
        self.log_file = None
        if self.devices.enabled('rig'):
            self._init_log(self.cfg.sync.freq_log_path)
            self._last_rig_change = None
            self._rig_reported = True
        else:
            self.logger.log(
                "[LOG ERROR] Rig not configured, but logfile specified. Turning off logging", "ERROR")

                                                                                        # Direct mode - last change wins
        self._sync_time = 0.0
        self._sync_lead = None
                                                                                        # Poller for non-blocking I/O
        self._poller = select.poll()
        self._fd_map = {}

    # # # # # # # # #
    # # #  API  # # #
    # # # # # # # # #

    def tick(self, now):
        """Perform a single iteration: update UI, manage connections, send/receive data, process synchronisation."""
        if self._shutdown:                                                              # Return on shutdown
            return

        events = self._poller.poll(0)                                                   # Poll all sockets
        for rdo in self.radio.values():                                                 # Clear old events
            rdo['events'] = []

        for fd, flag in events:                                                         # Assign new events to radio{}
            role, sock = self._fd_map.get(fd, (None, None))
            if role:
                self.radio[role]['events'].append((fd, flag))

        for role, rdo in self.radio.items():                                            ##### Loop per role (rig, gqrx)

            evs = rdo.get('events', [])
            if any(flag & (select.POLLHUP | select.POLLERR) for _, flag in evs):        # Handle poll errors
                self._cleanup_socket(role)
                continue
            if any(flag & select.POLLIN for _, flag in evs):                            # Read and process incoming data
                self._process_incoming(role, now)
            if any(flag & select.POLLOUT for _, flag in evs):                           # Write outgoing data
                self._send_command(role, now)

            if rdo['freq_cur'] is None:                                                 # Ensure that we have a freq
                if self.ifreq is not None and role == 'gqrx':
                    rdo['command'] = b"LNB_LO\n"
                else:
                    rdo['command'] = b"f\n"

            self._freq_query(role, now)                                                 # Query frequency
            self._freq_set(role)                                                        # Set frequency
            self.reconnect_socket(now, role)                                            # Socket keep-alive
            self._freq_check_timeout(role, now)                                         # Reply timeouts

                                                                                        ##### Once per tick actions
        self._log_rig_change(self.cfg.sync.wait_before_log_rigfreq, now)                # Log Frequency
        self._apply_sync_actions(now)                                                   # Apply sync actions
        self._update_sync_state()                                                       # Update sync state (On/Off)
        self._update_band()                                                             # Update band name
        self._update_ui()                                                               # Update display

    def nudge(self, delta_hz):
        """Adjust frequency by the sum of UP/DOWN commands from input devices received since last command send."""
        try:
            # If rig present, nudge rig. If rig not present, nudge gqrx.
            for role in ('rig', 'gqrx'):
                rdo = self.radio[role]
                if rdo['sock'] is not None and self.devices.enabled(role):
                    rdo['freq_delta'] += delta_hz
                    if abs(rdo['freq_delta']) > self.step.get_step() * self.cfg.sync.nudge_buffer:
                        rdo['freq_delta'] -= delta_hz
                    self.logger.log(f"{role.upper()} NUDGE {rdo['freq_delta']}", "DEBUG")
                    break
        except (KeyError, AttributeError, TypeError) as e:
            self.logger.log(f"[NUDGE ERROR]: {e}", "CRITICAL")

    def set_sync_mode(self, state):
        """Enable or disable synchronization on user request"""
        self._wanted_sync = state
        if self.radio['rig']['sock'] is None or self.radio['gqrx']['sock'] is None:
            state = False
        self.sync_on = state

    def reconnect_socket(self, now, role):
        """ If socket not present for registered device, create a new one. """
        rdo = self.radio[role]
        if self.devices.enabled(role) and rdo['sock'] is None and now - rdo['recon_timestamp'] > rdo['recon_interval']:
            rdo['sock'] = self._connect_socket(rdo['host'], rdo['port'])
            self._register_socket(role, rdo['sock'])
            rdo['recon_timestamp'] = now
            self.logger.log(f"Created new socket for {role}", "DEBUG")
        elif not self.devices.enabled(role) and rdo['sock']:
            self._cleanup_socket(role)
            self.logger.log(f"Destroyed socket for  {role}", "WARNING")

    def shutdown(self, role=None):
        """Shutdown sockets, clear internal state, prevent further ticks."""
        if role is None:                                                                # Full shutdown
            self._shutdown = True                                                       # Prevent tick()
            if self.log_file is not None:                                               # Close Logfile
                try:
                    self.log_file.close()
                except (OSError, ValueError):
                    pass
                try:
                    self.logger.close()
                except Exception:
                    pass
                try:                                                                    # Reset poller and FD map
                    self._poller = select.poll()
                except OSError:
                    pass
                self._fd_map.clear()

        if role not in self.radio:                                                      ##### Per role shutdown
            keys = list(self.radio.keys())
        else:
            keys = [role]
        for key in keys:
            rdo = self.radio[key]
            if rdo['sock']:                                                             # Unregister & close socket
                self._cleanup_socket(key)

            rdo.update({                                                                # Reset status
                'sock'                        : None,
                'recon_timestamp'             : 0.0,
                'freq_cur'                    : None,
                'freq_prev'                   : 0,
                'freq_sent'                   : None,
                'freq_delta'                  : 0,
                'freq_delta_sent'             : 0,
                'is_busy'                     : None,
                'send_timestamp'              : 0.0,
                'recv_buf'                    : bytearray(),
                'command'                     : None,
                'events'                      : []
            })

    # # # # # # # # # # # # #
    # # #   UI Update   # # #
    # # # # # # # # # # # # #

    def _update_ui(self):
        """ Write values to user interface periodically """
        if self.display is None:
            return
        try:
            self.display.set_sync_mode(self.sync_on)
            for role, rdo in self.radio.items():
                if rdo['sock'] is None:
                    freq = None
                else:
                    base = rdo['freq_cur']
                    # We keep the LO_Freq in the gqrx['freq_cur'], but we convert it to main frequency for display
                    if self.ifreq is not None and base is not None and role == 'gqrx':
                        freq = base + abs(int(self.ifreq * 1e6))
                    else:
                        freq = base
                setter = getattr(self.display, f"set_{role}")
                setter(freq, rdo['sock'])
        except (AttributeError, TypeError, KeyError) as e:
            self.logger.log(f"[DISPLAY ERROR] {e}", "CRITICAL")

    # # # # # # # # # # # # # # # #
    # # #   Synchronisation   # # #
    # # # # # # # # # # # # # # # #

    def _update_sync_state(self):
        """Disable sync on only one active radio; restore if both present, and it has been enabled before."""
        if any(rdo['sock'] is None for rdo in self.radio.values()):
            self.sync_on = False
        else:
            if self._wanted_sync and not self.sync_on:
                self.sync_on = True

    def _update_band(self):
        """Update band information if either frequency has changed."""
        if self.display is None:
            return

        rig = self.radio['rig']
        gqrx = self.radio['gqrx']
        rig_changed = rig['freq_cur'] != rig['freq_prev']
        gqrx_changed = gqrx['freq_cur'] != gqrx['freq_prev']

        if not (rig_changed or gqrx_changed):
            return

        freq_hz = rig['freq_cur'] or gqrx['freq_cur']
        if freq_hz is None:
            return

        band_name = Bands().band_name(freq_hz / 1_000_000)
        self.display.set_band_name(band_name)

    def _apply_sync_actions(self, now):
        """ Perform synchronization actions """

        rig = self.radio['rig']
        gqrx = self.radio['gqrx']
        rig_changed = rig['freq_cur'] != rig['freq_prev']
        gqrx_changed = gqrx['freq_cur'] != gqrx['freq_prev']

        if (not self.sync_on                                                            # Run Conditions
                or rig['sock'] is None
                or not self.devices.enabled('rig')
                or gqrx['sock'] is None
                or not self.devices.enabled('gqrx')
                or rig['freq_cur'] is None
                or (gqrx['freq_cur'] is None and self.ifreq is None)):
            return

        if self.ifreq is None:                                                          # Direct Mode

            if rig_changed:
                if not (self._sync_lead == 'gqrx' and now - self._sync_time < self.cfg.sync.sync_debounce_time):
                    self._sync_lead = 'rig'
                    self._sync_time = now
                    rig['freq_prev'] = rig['freq_cur']
                    gqrx['freq_sent'] = rig['freq_cur']
                    gqrx['command'] = self._build_cat_cmd(rig['freq_cur'])
                    self.logger.log(f"RIG CHANGE DIRECT SYNC {rig['freq_cur']}", "DEBUG")

            elif gqrx_changed:
                if not (self._sync_lead == 'rig' and now - self._sync_time < self.cfg.sync.sync_debounce_time):
                    self._sync_lead = 'gqrx'
                    self._sync_time = now
                    gqrx['freq_prev'] = gqrx['freq_cur']
                    rig['freq_sent'] = gqrx['freq_cur']
                    rig['command'] = self._build_cat_cmd(gqrx['freq_cur'])
                    self.logger.log(f"GQRX CHANGE DIRECT SYNC {rig['freq_cur']}", "DEBUG")
            return

        else:                                                                           # Ifreq mode

            if rig_changed:
                lo_freq = rig['freq_cur'] - abs(int(self.ifreq * 1e6))
                if lo_freq != gqrx['freq_cur']:
                    rig['freq_prev'] = rig['freq_cur']
                    gqrx['freq_sent'] = lo_freq
                    gqrx['command'] = self._build_cat_cmd(lo_freq, is_lo=True)
                    self.logger.log(f"RIG CHANGE IFREQ SYNC {rig['freq_cur']}", "DEBUG")

    # # # # # # # # # # # # # # # # # # # # #
    # # #   I/O, Frequency get / set    # # #
    # # # # # # # # # # # # # # # # # # # # #

    @staticmethod
    def _build_cat_cmd(freq, is_lo=False):
        """Construct CAT command to set Frequency or Local Oscillator."""
        prefix = b"LNB_LO " if is_lo else b"F "
        return prefix + str(freq).encode() + b"\n"

    def _freq_set(self, role):
        """Set frequency for each role if a delta is queued and device is enabled"""
        rdo = self.radio[role]

        if (rdo['sock'] is None                                                          # Run conditions
                or not self.devices.enabled(role)
                or rdo['is_busy'] is not None
                or rdo['freq_cur'] is None
                or not rdo['freq_delta'] and rdo['freq_sent'] is None):
            return

        new_freq = rdo['freq_cur'] + rdo['freq_delta']                                  # FreqSetCmd, overwrites
        rdo['freq_delta_sent'] = rdo['freq_delta']
        rdo['freq_sent'] = new_freq
        rdo['command'] = self._build_cat_cmd(new_freq)
        self.logger.log(f"{role.upper()} FREQ SET CMD {new_freq}", "DEBUG")

    def _freq_query(self, role, now):
        """ Query frequency  """
        rdo = self.radio[role]

        if ((now - rdo['send_timestamp']) < rdo['freq_query_interval']                   # Run conditions
                or rdo['sock'] is None
                or rdo['is_busy'] is not None
                or self.ifreq is not None and role == 'gqrx'): # No freq query to gqrx in ifreq mode.
            return

        if rdo['command'] is None:                                                       # FreqQueryCmd, not overwriting
            self.logger.log(f"{role.upper()} FREQ QUERY CMD", "DEBUG")
            rdo['command'] = b"f\n"

    def _freq_check_timeout(self, role, now):
        """ Check command-reply-timeouts """
        rdo = self.radio[role]
        if rdo['is_busy'] is not None:
            if now - rdo['is_busy'] > rdo['timeout']:
                self.logger.log(f"[TIMEOUT ERROR] {role.upper()} did not ack in {rdo['timeout']}s", "DEBUG")
                rdo['is_busy'] = None
                rdo['freq_sent'] = None
                rdo['freq_delta_sent'] = 0
                rdo['freq_delta'] = 0

    def _send_command(self, role, now):
        """Send pending commands for the specified role when its socket is writable."""
        rdo = self.radio[role]
        if (rdo['sock'] is None                                                         # Run conditions
                or rdo['command'] is None
                or not self.devices.enabled(role)):
            return

        try:                                                                            # Send to Socket
            rdo['sock'].sendall(rdo['command'])
        except BlockingIOError:
            return
        except OSError as e:
            self.logger.log(f"{role.upper()} SEND ERROR {e}", "DEBUG")
            self._cleanup_socket(role)
            return

        self.logger.log(f"{role.upper()} SEND {rdo['command']}", "DEBUG")
        rdo['is_busy'] = now                                                            # Set busy flag and command
        rdo['send_timestamp'] = now
        rdo['command'] = None

    def _process_incoming(self, role, now):
        """Receive data from Rig/Gqrx and buffer messages."""
        rdo = self.radio[role]
        try:                                                                            # Read socket
            data = rdo['sock'].recv(self.cfg.sync.read_buffer_size)
        except OSError as e:
            self.logger.log(f"{role.upper()} RECV ERROR] {e}", "DEBUG")
            self._cleanup_socket(role)
            return
        if not data:
            self.logger.log(f"[DEBUG] {role.upper()} SOCKET DIED", "DEBUG")
            self._cleanup_socket(role)
            return

        if rdo['is_busy'] is None:                                                      # Got response, but not busy
            self.logger.log(f"{role.upper()} ERROR Response while not busy: {data}", "DEBUG")
            return

        buf = rdo['recv_buf']                                                           # Build buffer and trim it
        buf.extend(data)
        if len(buf) > self.cfg.sync.max_read_buffer_bytes:
            del buf[0:len(buf) - self.cfg.sync.max_read_buffer_bytes]

        parts = buf.split(b'\n')
        complete = parts[:-1]
        incomplete = parts[-1]
        for part in complete:
            if not part:
                continue

            is_error = False
            freq = None

            self.logger.log(f"{role.upper()} RECEIVED {part.decode()}", "DEBUG")
            if part.startswith(b"RPRT"):  # READ REPORT
                try:
                    _, code = part.split(b" ", 1)
                except ValueError:
                    self.logger.log(
                        f"ERROR {role.upper()} MALFORMED RPRT RESPONSE: {part.decode()}", "DEBUG")
                    is_error = True
                    code = None

                if code and code == b"0":                                               ##### Success Report
                    self.logger.log(f"{role.upper()} RPRT SUCCESS", "DEBUG")
                    if rdo['freq_sent'] is not None:
                        rdo['freq_prev'] = rdo['freq_cur']                              # Set internal state on success
                        rdo['freq_cur'] = rdo['freq_sent']
                        rdo['freq_sent'] = None

                    if rdo['freq_delta_sent']:
                        rdo['freq_delta'] -= rdo['freq_delta_sent']
                        rdo['freq_delta_sent'] = 0
                    else:
                        rdo['freq_delta'] = 0
                else:                                                                   # Error Report
                    is_error = True
                    self.logger.log(f"{role.upper()} ERROR RPRT {code.decode()}", "DEBUG")
            else:
                try:                                                                    ##### READ FREQUENCY
                    freq = int(part)
                except ValueError:
                    is_error = True
                    freq = None
                    self.logger.log(f"{role.upper()} ERROR RESPONSE UNKNOWN: {part.decode()}", "DEBUG")

            if freq is not None:
                if freq != rdo['freq_prev']:                                            # New frequency present
                    if role == 'rig':                                                   # Logging
                        self._last_rig_change = now
                        self._rig_reported = False
                    rdo['freq_prev'] = rdo['freq_cur']                                  # Set frequencies
                    rdo['freq_cur'] = freq

            if is_error:                                                                # Clear sent and delta on error
                self.logger.log(f"{role.upper()} ERROR IN RECEIVED DATA", "DEBUG")
                rdo['freq_sent'] = None
                rdo['freq_delta'] = 0

            rdo['recv_buf'] = bytearray(incomplete)                                     # Preserve incomplete tail
            rdo['is_busy'] = None                                                       # Clear Busy

    # # # # # # # # # # # # # #
    # # # Socket Handling # # #
    # # # # # # # # # # # # # #

    @staticmethod
    def _connect_socket(host, port):
        """Create non-blocking socket and connect to it"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setblocking(False)
        sock.connect_ex((host, port))
        return sock

    def _register_socket(self, role, sock):
        """Register a socket with the poller."""
        fd = sock.fileno()
        self._poller.register(fd, select.POLLIN | select.POLLOUT)
        self._fd_map[fd] = (role, sock)

    def _cleanup_socket(self, role):
        """Unregister, close, clear buffer, disable sync."""
        rdo = self.radio[role]
        sock = rdo['sock']

        if sock:
            try:                                                                        # unregister from poller
                fd = sock.fileno()
                self._poller.unregister(fd)
                self._fd_map.pop(fd, None)
            except (OSError, ValueError):
                pass
            try:                                                                        # close socket
                sock.close()
            except OSError:
                pass

        rdo['sock'] = None                                                              # reset state
        rdo['recv_buf'] = bytearray()
        self.sync_on = False

    # # # # # # # # # # # # # # # # #
    # # #   Frequency Logging   # # #
    # # # # # # # # # # # # # # # # #

    def _log_rig_change(self, wait, now):
        """Log Rig frequency, ."""
        if self.log_file is not None and self._last_rig_change is not None and not self._rig_reported:
            if now - self._last_rig_change > wait:
                ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now))
                line = f"{ts} {self.radio['rig']['freq_cur']}\n"
                self._write_log(line)
                self._rig_reported = True

    def _init_log(self, logfile_path):
        """Initialize logfile: open and write header if path given."""
        if not logfile_path:
            return
        try:
            self.log_file = open(logfile_path, 'a')
        except (FileNotFoundError, PermissionError) as e:

            self.logger.log(f"[LOGFILE ERROR] {e}", "CRITICAL")
            self.log_file = None

        header = time.strftime(
            "# # # # # # # # # PanSyncer log started %Y-%m-%d %H:%M:%S UTC # # # # # # # # # \n",
            time.gmtime()
        )
        self._write_log(header)

    def _write_log(self, line: str):
        """Write a line to logfile."""
        if self.log_file is not None:
            try:
                self.log_file.write(line)
                self.log_file.flush()
            except IOError as e:
                self.logger.log(f"[LOGGING ERROR] {e}", "WARNING")
                self.log_file = None
