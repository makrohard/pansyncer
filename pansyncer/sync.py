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
    nudge_buffer:               int           = 10
    read_buffer_size:           int           = 1024
    max_read_buffer_bytes:      int           = 64 * read_buffer_size

class SyncManager:
    """SyncManager handles synchronization between Rig and Gqrx clients."""

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
        self.ifreq_hz = int(round(abs(self.ifreq * 1_000_000))) if self.ifreq is not None else None
        self.bands = Bands(self.cfg.bands)
        self._shutdown = False

        self.radio = {
            'rig': {
                'host'                        : self.cfg.sync.rig_host,
                'port'                        : self.cfg.sync.rig_port,
                'sock'                        : None,
                'connected'                   : False,
                'recon_interval'              : self.cfg.sync.rig_socket_recon_interval,
                'recon_timestamp'             : 0.0,
                'freq_cur'                    : None,
                'freq_processed'              : None,
                'freq_sent'                   : None,
                'freq_queued'                 : None,
                'freq_queued_is_lo'           : False,
                'freq_query_interval'         : self.cfg.sync.rig_freq_query_interval,
                'is_busy'                     : None,
                'send_timestamp'              : 0.0,
                'timeout'                     : self.cfg.sync.rig_timeout,
                'recv_buf'                    : bytearray(),
                'query'                       : None,
                'events'                      : []
            },
            'gqrx': {
                'host'                        : self.cfg.sync.gqrx_host,
                'port'                        : self.cfg.sync.gqrx_port,
                'sock'                        : None,
                'connected'                   : False,
                'recon_interval'              : self.cfg.sync.gqrx_socket_recon_interval,
                'recon_timestamp'             : 0.0,
                'freq_cur'                    : None,
                'freq_processed'              : None,
                'freq_sent'                   : None,
                'freq_queued'                 : None,
                'freq_queued_is_lo'           : False,
                'freq_query_interval'         : self.cfg.sync.gqrx_freq_query_interval,
                'is_busy'                     : None,
                'send_timestamp'              : 0.0,
                'timeout'                     : self.cfg.sync.gqrx_timeout,
                'recv_buf'                    : bytearray(),
                'query'                       : None,
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
                                                                                        # Frequency Logger
        self.log_file = None
        self._last_rig_change = None
        self._rig_reported = True
        if self.devices.enabled('rig'):
            self._init_log(self.cfg.sync.freq_log_path)
        elif self.cfg.sync.freq_log_path:
            self.logger.log(
                "[LOG ERROR] Rig not configured, but logfile specified. Turning off logging", "ERROR")

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
            role = self._fd_map.get(fd)
            if role:
                self.radio[role]['events'].append((fd, flag))

        for role, rdo in self.radio.items():                                            ##### Read / reconnect loop

            evs = rdo.get('events', [])
            if any(flag & (select.POLLHUP | select.POLLERR | select.POLLNVAL)
                    for _, flag in evs):                                                # Handle poll errors
                self._cleanup_socket(role)
                self.reconnect_socket(now, role)                                        # Socket keep-alive
                continue
            if any(flag & select.POLLIN for _, flag in evs):                            # Read and process incoming data
                self._process_incoming(role, now)

            self.reconnect_socket(now, role)                                            # Socket keep-alive
            self._freq_check_timeout(role, now)                                         # Reply timeouts

        self._update_sync_state()                                                       # Update sync state (On/Off)
        self._apply_sync_actions()                                                      # Apply sync actions

        for role, rdo in self.radio.items():                                            ##### Queue frequency queries

            if (rdo['freq_cur'] is None
                    and rdo['freq_queued'] is None
                    and rdo['query'] is None
                    and rdo['is_busy'] is None):                                        # Ensure that we have a freq
                if self.ifreq is not None and role == 'gqrx':
                    rdo['query'] = b"LNB_LO\n"
                else:
                    rdo['query'] = b"f\n"
            self._freq_query(role, now)                                                 # Query frequency

        for role, rdo in self.radio.items():                                            ##### Send commands
            evs = rdo.get('events', [])
            if any(flag & select.POLLOUT for _, flag in evs):                           # Write outgoing data
                if not self._check_connect(role):                                       # Check connect result
                    continue
                self._send_query(role, now)
                                                                                        ##### Once per tick actions
        self._log_rig_change(self.cfg.sync.wait_before_log_rigfreq, now)                # Log Frequency
        self._update_band()                                                             # Update band name
        self._update_ui()                                                               # Update display

    def nudge(self, delta_hz):
        """Queue a live frequency change from keyboard, mouse, or external VFO knob."""
        try:
            # If rig present, nudge rig. If rig not present, nudge gqrx.
            for role in ('rig', 'gqrx'):
                rdo = self.radio[role]
                if rdo['sock'] is not None and rdo['connected'] and self.devices.enabled(role):
                    base_freq = self._effective_freq(role)
                    if base_freq is None:
                        return

                    new_freq = base_freq + delta_hz

                    if rdo['freq_cur'] is not None:
                        max_delta = abs(int(self.step.get_step())) * self.cfg.sync.nudge_buffer
                        if max_delta > 0 and abs(new_freq - rdo['freq_cur']) > max_delta:
                            self.logger.log(f"{role.upper()} NUDGE BUFFER FULL", "DEBUG")
                            return

                    is_lo = self.ifreq is not None and role == 'gqrx'
                    if self._queue_set(role, new_freq, is_lo=is_lo):
                        self.logger.log(f"{role.upper()} NUDGE QUEUED {new_freq}", "DEBUG")
                    break
        except (KeyError, AttributeError, TypeError, ValueError) as e:
            self.logger.log(f"[NUDGE ERROR]: {e}", "CRITICAL")

    def get_frequency(self):
        """Return current main frequency."""
        try:
            rig = self.radio['rig']
            gqrx = self.radio['gqrx']
            rig_ok = (
                    rig['sock'] is not None
                    and rig['connected']
                    and rig['freq_cur'] is not None
            )
            gqrx_ok = (
                    gqrx['sock'] is not None
                    and gqrx['connected']
                    and gqrx['freq_cur'] is not None
            )
            if rig_ok:
                return rig['freq_cur']
            if gqrx_ok:
                if self.ifreq is not None:
                    return gqrx['freq_cur'] + self.ifreq_hz
                return gqrx['freq_cur']
            return None
        except (KeyError, TypeError) as e:
            self.logger.log(f"SYNC GET FREQ ERROR {e}", "ERROR")
            return None

    def set_frequency(self, freq_hz, role=None):
        """Set absolute main frequency (Hz)."""
        try:
            freq_hz = int(round(freq_hz)) if isinstance(freq_hz, float) else int(freq_hz)
            if self.ifreq is not None:
                if role in self.radio:
                    tgt = role
                else:
                    rig_ok = (
                        self.radio['rig']['sock'] is not None
                        and self.radio['rig']['connected']
                        and self.devices.enabled('rig')
                    )
                    gqx_ok = (
                        self.radio['gqrx']['sock'] is not None
                        and self.radio['gqrx']['connected']
                        and self.devices.enabled('gqrx')
                    )
                    tgt = 'rig' if rig_ok else ('gqrx' if gqx_ok else None)

                if tgt is None:
                    return False

                if tgt == 'gqrx':
                    ifreq_hz = self.ifreq_hz
                    lo_freq = freq_hz - ifreq_hz
                    return self._queue_set('gqrx', lo_freq, is_lo=True)

                return self._queue_set(tgt, freq_hz)

            if role in self.radio:
                tgt = role
            else:
                rig_ok = (self.radio['rig']['sock'] is not None
                    and self.radio['rig']['connected']
                    and self.devices.enabled('rig'))
                gqx_ok = (self.radio['gqrx']['sock'] is not None
                    and self.radio['gqrx']['connected']
                    and self.devices.enabled('gqrx'))
                tgt = 'rig' if rig_ok else ('gqrx' if gqx_ok else None)
            if tgt is None:
                return False
            return self._queue_set(tgt, freq_hz)
        except (ValueError, TypeError, KeyError) as e:
            self.logger.log(f"SYNC SET FREQ ERROR {e}", "ERROR")
            return False

    def band_step(self, direction):
        """Step to next or previous band."""
        try:
            cur = self.get_frequency()
            if cur is None:
                return False
            freq_mhz = cur / 1_000_000
            goto_mhz = self.bands.step(freq_mhz, +1) if direction > 0 else self.bands.step(freq_mhz, -1)
            if not goto_mhz:
                return False

            return self.set_frequency(int(round(goto_mhz * 1_000_000)))
        except (TypeError, ValueError, KeyError) as e:
            self.logger.log(f"[BAND STEP ERROR] {e}", "DEBUG")
            return False

    def set_sync_mode(self, state):
        """Enable or disable synchronization on user request"""
        self._wanted_sync = state
        if (self.radio['rig']['sock'] is None
                or not self.radio['rig']['connected']
                or self.radio['gqrx']['sock'] is None
                or not self.radio['gqrx']['connected']):
            state = False
        self.sync_on = state

    def reconnect_socket(self, now, role):
        """If socket not present for registered device, create a new one."""
        rdo = self.radio[role]
        if self.devices.enabled(role) and rdo['sock'] is None and now - rdo['recon_timestamp'] > rdo['recon_interval']:
            rdo.update({                                                                # Reset stale state
                'connected'                   : False,
                'freq_cur'                    : None,
                'freq_processed'              : None,
                'freq_sent'                   : None,
                'freq_queued'                 : None,
                'freq_queued_is_lo'           : False,
                'is_busy'                     : None,
                'recv_buf'                    : bytearray(),
                'query'                       : None,
                'events'                      : []
            })

            if self.ifreq is not None and role == 'gqrx':
                self.radio['rig']['freq_processed'] = None                              # Force LO resync

            rdo['recon_timestamp'] = now
            sock = None
            try:
                sock = self._connect_socket(rdo['host'], rdo['port'])
                self._register_socket(role, sock)
            except OSError as e:
                self.logger.log(f"{role.upper()} CONNECT CREATE ERROR {e}", "DEBUG")
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
                rdo['sock'] = None
                return

            rdo['sock'] = sock
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
                'connected'                   : False,
                'recon_timestamp'             : 0.0,
                'freq_cur'                    : None,
                'freq_processed'              : None,
                'freq_sent'                   : None,
                'freq_queued'                 : None,
                'freq_queued_is_lo'           : False,
                'is_busy'                     : None,
                'send_timestamp'              : 0.0,
                'recv_buf'                    : bytearray(),
                'query'                       : None,
                'events'                      : []
            })

        if role is None:
            try:                                                                        # Reset poller and FD map
                self._poller = select.poll()
            except OSError:
                pass
            self._fd_map.clear()

    # # # # # # # # # # # # #
    # # #   UI Update   # # #
    # # # # # # # # # # # # #

    def _update_ui(self):
        """Write values to user interface periodically"""
        if self.display is None:
            return
        try:
            self.display.set_sync_mode(self.sync_on)
            for role, rdo in self.radio.items():
                if rdo['sock'] is None or not rdo['connected']:
                    freq = None
                    sock = None
                else:
                    sock = rdo['sock']
                    base = rdo['freq_cur']
                    # We keep the LO_Freq in the gqrx['freq_cur'], but we convert it to main frequency for display
                    if self.ifreq is not None and base is not None and role == 'gqrx':
                        freq = base + self.ifreq_hz
                    else:
                        freq = base
                setter = getattr(self.display, f"set_{role}")
                setter(freq, sock)
        except (AttributeError, TypeError, KeyError) as e:
            self.logger.log(f"[DISPLAY ERROR] {e}", "CRITICAL")

    # # # # # # # # # # # # # # # #
    # # #   Synchronisation   # # #
    # # # # # # # # # # # # # # # #

    def _update_sync_state(self):
        """Disable sync on only one active radio; restore if both present, and it has been enabled before."""
        if any(rdo['sock'] is None or not rdo['connected'] for rdo in self.radio.values()):
            self.sync_on = False
        else:
            if self._wanted_sync and not self.sync_on:
                self.sync_on = True

    def _update_band(self):
        """Update band information."""
        if self.display is None or self.cfg.display.small_display:
            return
        freq_hz = self.get_frequency()
        if freq_hz is None:
            self.display.set_band_name("")
            return
        band_name = self.bands.band_name(freq_hz / 1_000_000)
        self.display.set_band_name(band_name)

    def _effective_freq(self, role):
        """Return the newest intended frequency for a radio."""
        rdo = self.radio[role]
        if rdo['freq_queued'] is not None:
            return rdo['freq_queued']
        if rdo['freq_sent'] is not None:
            return rdo['freq_sent']
        return rdo['freq_cur']

    def _confirmed_freq(self, role, freq_hz):
        """Return True if this radio has confirmed this frequency."""
        rdo = self.radio[role]
        return (
            rdo['freq_cur'] == freq_hz
            and rdo['freq_sent'] is None
            and rdo['freq_queued'] is None
        )

    def _freq_unprocessed(self, role):
        """Return True if the newest intended frequency has not yet been handled by sync."""
        freq = self._effective_freq(role)
        rdo = self.radio[role]
        return freq is not None and freq != rdo['freq_processed']

    def _queue_set(self, role, freq_hz, is_lo=False, mark_processed=False):
        """Queue the latest wanted set frequency."""
        rdo = self.radio[role]

        if rdo['sock'] is None or not rdo['connected'] or not self.devices.enabled(role):
            return False

        freq_hz = int(freq_hz)

        if mark_processed:
            rdo['freq_processed'] = freq_hz

        if rdo['freq_sent'] == freq_hz:                                               # Already in flight
            rdo['freq_queued'] = None
            rdo['freq_queued_is_lo'] = False
            rdo['query'] = None                                                       # Drop pending query
            return True

        rdo['freq_queued'] = freq_hz
        rdo['freq_queued_is_lo'] = is_lo
        rdo['query'] = None                                                           # Set overwrites query
        self.logger.log(f"{role.upper()} SET QUEUED {freq_hz}", "DEBUG")
        return True

    def _apply_sync_actions(self):
        """Perform synchronization actions."""

        rig = self.radio['rig']
        gqrx = self.radio['gqrx']
        rig_changed = self._freq_unprocessed('rig')
        gqrx_changed = self._freq_unprocessed('gqrx')

        if (not self.sync_on                                                            # Run Conditions
                or rig['sock'] is None
                or not rig['connected']
                or not self.devices.enabled('rig')
                or gqrx['sock'] is None
                or not gqrx['connected']
                or not self.devices.enabled('gqrx')
                or self._effective_freq('rig') is None
                or (self._effective_freq('gqrx') is None and self.ifreq is None)):
            return

        if self.ifreq is None:                                                          # Direct Mode
            if rig_changed:
                target_freq = self._effective_freq('rig')
                if self._effective_freq('gqrx') == target_freq:
                    if self._confirmed_freq('gqrx', target_freq):
                        rig['freq_processed'] = target_freq
                        gqrx['freq_processed'] = target_freq
                    return
                if not self._queue_set('gqrx', target_freq, mark_processed=True):
                    return
                self.logger.log(f"RIG CHANGE DIRECT SYNC {target_freq}", "DEBUG")

            elif gqrx_changed:
                target_freq = self._effective_freq('gqrx')
                if self._effective_freq('rig') == target_freq:
                    if self._confirmed_freq('rig', target_freq):
                        gqrx['freq_processed'] = target_freq
                        rig['freq_processed'] = target_freq
                    return
                if not self._queue_set('rig', target_freq, mark_processed=True):
                    return
                self.logger.log(f"GQRX CHANGE DIRECT SYNC {target_freq}", "DEBUG")
            return

        else:                                                                           # iFreq mode
            if rig_changed:
                rig_freq = self._effective_freq('rig')
                lo_freq = rig_freq - self.ifreq_hz
                if self._effective_freq('gqrx') == lo_freq:
                    if self._confirmed_freq('gqrx', lo_freq):
                        rig['freq_processed'] = rig_freq
                        gqrx['freq_processed'] = lo_freq
                    return
                if not self._queue_set('gqrx', lo_freq, is_lo=True, mark_processed=True):
                    return
                self.logger.log(f"RIG CHANGE IFREQ SYNC {rig_freq}", "DEBUG")

    # # # # # # # # # # # # # # # # # # # # #
    # # #   I/O, Frequency get / set    # # #
    # # # # # # # # # # # # # # # # # # # # #

    @staticmethod
    def _build_cat_cmd(freq, is_lo=False):
        """Construct CAT query to set Frequency or Local Oscillator."""
        prefix = b"LNB_LO " if is_lo else b"F "
        return prefix + str(freq).encode() + b"\n"

    def _freq_query(self, role, now):
        """Query frequency"""
        rdo = self.radio[role]

        if ((now - rdo['send_timestamp']) < rdo['freq_query_interval']                  # Run conditions
                or rdo['sock'] is None
                or rdo['is_busy'] is not None
                or rdo['freq_queued'] is not None
                or self.ifreq is not None and role == 'gqrx'):                          # No freq query to gqrx in ifreq mode.
            return

        if rdo['query'] is None:                                                        # FreqQueryCmd, not overwriting
            self.logger.log(f"{role.upper()} FREQ QUERY CMD", "DEBUG")
            rdo['query'] = b"f\n"

    def _freq_check_timeout(self, role, now):
        """Check query-reply-timeouts."""
        rdo = self.radio[role]
        if rdo['is_busy'] is None:
            return
        if now - rdo['is_busy'] <= rdo['timeout']:
            return
        self.logger.log(f"[TIMEOUT ERROR] {role.upper()} did not ack in {rdo['timeout']}s", "DEBUG")

        if rdo['freq_sent'] is not None:
            if rdo['freq_processed'] == rdo['freq_sent']:
                rdo['freq_processed'] = rdo['freq_cur']
            rdo['freq_sent'] = None

        rdo['recv_buf'] = bytearray()                                                   # Drop stale partial data
        rdo['is_busy'] = None

    def _send_query(self, role, now):
        """Send pending queries for the specified role when its socket is writable."""
        rdo = self.radio[role]

        if (rdo['sock'] is None                                                         # Run conditions
                or not rdo['connected']
                or rdo['is_busy'] is not None
                or not self.devices.enabled(role)):
            return

        if rdo['freq_queued'] is not None:                                              # Set has priority
            query = self._build_cat_cmd(rdo['freq_queued'], is_lo=rdo['freq_queued_is_lo'])
            is_set = True
        elif rdo['query'] is not None:
            query = rdo['query']
            is_set = False
        else:
            return

        try:                                                                            # Send to Socket
            rdo['sock'].sendall(query)
        except BlockingIOError:
            return
        except OSError as e:
            self.logger.log(f"{role.upper()} SEND ERROR {e}", "DEBUG")
            self._cleanup_socket(role)
            return

        if is_set:
            rdo['freq_sent'] = rdo['freq_queued']
            rdo['freq_queued'] = None
            rdo['freq_queued_is_lo'] = False

        self.logger.log(f"{role.upper()} SEND {query}", "DEBUG")
        rdo['is_busy'] = now                                                            # Set busy flag
        rdo['send_timestamp'] = now
        rdo['query'] = None

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
            rdo['recv_buf'] = bytearray()                                               # Drop stale response data
            return

        buf = rdo['recv_buf']                                                           # Build buffer and trim it
        buf.extend(data)
        if len(buf) > self.cfg.sync.max_read_buffer_bytes:
            del buf[0:len(buf) - self.cfg.sync.max_read_buffer_bytes]

        parts = buf.split(b'\n')
        complete = parts[:-1]
        incomplete = parts[-1]
        if not complete:
            rdo['recv_buf'] = bytearray(incomplete)                                     # Preserve incomplete tail
            return

        for part in complete:
            part = part.strip()
            if not part:
                continue

            is_error = False
            freq = None
            self.logger.log(f"{role.upper()} RECEIVED {part.decode(errors='replace')}", "DEBUG")

            if part.startswith(b"RPRT"):                                                # WRITE REPORT
                try:
                    _, code = part.split(b" ", 1)
                except ValueError:
                    self.logger.log(
                    f"ERROR {role.upper()} MALFORMED RPRT RESPONSE: {part.decode(errors='replace')}", "DEBUG")
                    is_error = True
                    code = None

                if code and code == b"0":                                                ##### Success Report
                    self.logger.log(f"{role.upper()} RPRT SUCCESS", "DEBUG")
                    if rdo['freq_sent'] is not None:
                        new_freq = rdo['freq_sent']
                        if new_freq != rdo['freq_cur']:
                            if role == 'rig':
                                self._last_rig_change = now
                                self._rig_reported = False
                            rdo['freq_cur'] = new_freq

                        rdo['freq_sent'] = None

                else:                                                                   # Error Report
                    is_error = True
                    code_text = code.decode() if code is not None else "UNKNOWN"
                    self.logger.log(f"{role.upper()} ERROR RPRT {code_text}", "DEBUG")

            else:
                try:                                                                    ##### READ FREQUENCY
                    freq = int(part)
                except ValueError:
                    is_error = True
                    freq = None
                    self.logger.log(f"{role.upper()} ERROR RESPONSE UNKNOWN: {part.decode(errors='replace')}", "DEBUG")

            if freq is not None:
                if freq != rdo['freq_cur']:                                             # New frequency present
                    if role == 'rig':                                                   # Logging
                        self._last_rig_change = now
                        self._rig_reported = False
                    rdo['freq_cur'] = freq

            if is_error:                                                                # Clear sent state on error
                self.logger.log(f"{role.upper()} ERROR IN RECEIVED DATA", "DEBUG")
                if rdo['freq_sent'] is not None:
                    if rdo['freq_processed'] == rdo['freq_sent']:
                        rdo['freq_processed'] = rdo['freq_cur']
                    rdo['freq_sent'] = None
        rdo['recv_buf'] = bytearray(incomplete)                                         # Preserve incomplete tail
        rdo['is_busy'] = None                                                           # Clear Busy

    # # # # # # # # # # # # # #
    # # # Socket Handling # # #
    # # # # # # # # # # # # # #

    def _check_connect(self, role):
        """Check non-blocking socket connect result."""
        rdo = self.radio[role]
        sock = rdo['sock']

        if sock is None:
            return False
        if rdo['connected']:
            return True
        try:
            err = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        except OSError as e:
            self.logger.log(f"{role.upper()} CONNECT CHECK ERROR {e}", "DEBUG")
            self._cleanup_socket(role)
            return False
        if err:
            self.logger.log(f"{role.upper()} CONNECT ERROR {err}", "DEBUG")
            self._cleanup_socket(role)
            return False
        rdo['connected'] = True
        self.logger.log(f"{role.upper()} CONNECTED", "DEBUG")
        return True

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
        self._fd_map[fd] = role

    def _cleanup_socket(self, role):
        """Unregister, close, clear buffer, disable sync."""
        rdo = self.radio[role]
        sock = rdo['sock']

        if sock:
            try:                                                                        # unregister from poller
                fd = sock.fileno()
                self._poller.unregister(fd)
                self._fd_map.pop(fd, None)
            except (OSError, ValueError, KeyError):
                pass
            try:                                                                        # close socket
                sock.close()
            except OSError:
                pass

        rdo.update({                                                                    # reset socket state
            'sock'                        : None,
            'connected'                   : False,
            'recv_buf'                    : bytearray(),
            'query'                       : None,
            'is_busy'                     : None,
            'freq_sent'                   : None,
            'freq_queued'                 : None,
            'freq_queued_is_lo'           : False,
            'freq_processed'              : rdo['freq_cur'],
            'events'                      : []
        })
        self.sync_on = False

    # # # # # # # # # # # # # # # # #
    # # #   Frequency Logging   # # #
    # # # # # # # # # # # # # # # # #

    def _log_rig_change(self, wait, now):
        """Log Rig frequency"""
        if self.log_file is None or self._last_rig_change is None or self._rig_reported:
            return
        freq = self.radio['rig']['freq_cur']
        if freq is None:
            return
        if now - self._last_rig_change > wait:
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
            line = f"{ts} {freq}\n"
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
        if self.log_file is None:
            return

        try:
            self.log_file.write(line)
            self.log_file.flush()
        except (OSError, ValueError) as e:
            failed_log_file = self.log_file
            self.log_file = None

            try:
                failed_log_file.close()
            except (OSError, ValueError):
                pass

            self.logger.log(f"[LOGGING ERROR] {e}", "WARNING")