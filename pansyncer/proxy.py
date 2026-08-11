"""
pansyncer proxy.py
Optional rigctld-protocol TCP server. Serves pansyncer's cached frequency to a
logger (e.g. CQRLOG) so the logger never polls the rig directly and cannot stall
when the rig does. Frequency is read from SyncManager; sets are forwarded to it.
Mode is not tracked by sync and is served from a held value (freq is the point).
Off by default. Enable with [proxy] enabled = true. CQRLOG: use "Simple Rig".
"""

import socket
import select
from dataclasses import dataclass
from typing import Optional
from pansyncer.logger import Logger

MAX_LINE = 4096                                                                     # drop clients that never send a newline

@dataclass
class ProxyConfig:
    """Default configuration"""
    enabled:      bool          = False
    host:         str           = "127.0.0.1"
    port:         int           = 4632
    mode:         str           = "USB"
    passband:     int           = 2400
    log_level:    str           = "INFO"
    logfile_path: Optional[str] = None

class RigctldProxy:
    """Non-blocking rigctld-protocol server backed by SyncManager's cached state."""

    def __init__(self, cfg, sync, display=None):
        self.cfg = cfg.proxy
        self.sync = sync
        self.enabled = self.cfg.enabled
        self.logger = Logger(name=__name__,
                             display=display,
                             level=self.cfg.log_level,
                             logfile_path=self.cfg.logfile_path)
        self._mode = self.cfg.mode
        self._passband = self.cfg.passband
        self._last_freq = None
        self._listen = None
        self.port = None
        self._poller = select.poll()
        self._clients = {}                                                          # fd -> {'sock', 'buf'}

        if not self.enabled:
            return
        try:
            self._listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._listen.setblocking(False)
            self._listen.bind((self.cfg.host, self.cfg.port))
            self._listen.listen(4)
            self.port = self._listen.getsockname()[1]
            self._poller.register(self._listen.fileno(), select.POLLIN)
            self.logger.log(f"rigctld proxy listening on {self.cfg.host}:{self.port}", "INFO")
        except OSError as e:
            self.logger.log(f"[PROXY ERROR] cannot listen on {self.cfg.host}:{self.cfg.port}: {e}", "ERROR")
            self._cleanup_listen()
            self.enabled = False

    # # # # # # # # #
    # # #  API  # # #
    # # # # # # # # #

    def tick(self, now):
        """Accept clients, read requests, answer from cached state. Non-blocking."""
        if not self.enabled:
            return
        for fd, flag in self._poller.poll(0):
            if self._listen is not None and fd == self._listen.fileno():
                self._accept()
            elif flag & (select.POLLHUP | select.POLLERR | select.POLLNVAL):
                self._drop_client(fd)
            elif flag & select.POLLIN:
                self._read_client(fd)

    def shutdown(self):
        """Close all client sockets and the listen socket."""
        for fd in list(self._clients):
            self._drop_client(fd)
        self._cleanup_listen()
        self.enabled = False
        try:
            self.logger.close()
        except Exception:
            pass

    # # # # # # # # # # # # # #
    # # # Socket Handling # # #
    # # # # # # # # # # # # # #

    def _accept(self):
        """Accept any pending client connections."""
        while True:
            try:
                conn, _ = self._listen.accept()
            except BlockingIOError:
                return
            except OSError:
                return
            conn.setblocking(False)
            self._poller.register(conn.fileno(), select.POLLIN)
            self._clients[conn.fileno()] = {'sock': conn, 'buf': bytearray()}

    def _read_client(self, fd):
        """Read available data from a client and answer complete command lines."""
        client = self._clients.get(fd)
        if client is None:
            return
        try:
            data = client['sock'].recv(1024)
        except BlockingIOError:
            return
        except OSError:
            self._drop_client(fd)
            return
        if not data:
            self._drop_client(fd)
            return

        buf = client['buf']
        buf.extend(data)
        parts = buf.split(b'\n')
        client['buf'] = bytearray(parts[-1])                                        # keep incomplete tail
        if len(client['buf']) > MAX_LINE:                                           # runaway line, drop client
            self._drop_client(fd)
            return
        for raw in parts[:-1]:
            line = raw.decode(errors='replace').strip()
            if not line:
                continue
            reply = self._handle(line)
            if reply and not self._send(fd, reply):
                return

    def _send(self, fd, reply):
        """Send a reply to a client. Return False if the client was dropped."""
        client = self._clients.get(fd)
        if client is None:
            return False
        try:
            client['sock'].sendall(reply.encode())
            return True
        except OSError:
            self._drop_client(fd)
            return False

    def _drop_client(self, fd):
        """Unregister and close a client socket."""
        client = self._clients.pop(fd, None)
        try:
            self._poller.unregister(fd)
        except (KeyError, OSError, ValueError):
            pass
        if client is not None:
            try:
                client['sock'].close()
            except OSError:
                pass

    def _cleanup_listen(self):
        """Unregister and close the listen socket."""
        if self._listen is None:
            return
        try:
            self._poller.unregister(self._listen.fileno())
        except (KeyError, OSError, ValueError):
            pass
        try:
            self._listen.close()
        except OSError:
            pass
        self._listen = None

    # # # # # # # # # # # # #
    # # # rigctld protocol  #
    # # # # # # # # # # # # #

    def _handle(self, line):
        """Map one rigctld command line to a reply string."""
        extended = line.startswith('+')                                             # '+\cmd' verbose form
        if extended:
            line = line[1:].lstrip()
        if line.startswith('\\'):
            line = line[1:]
        parts = line.split()
        if not parts:
            return "RPRT -1\n"
        cmd, args = parts[0], parts[1:]

        if cmd in ('f', 'get_freq'):
            return self._reply_get_freq(extended)
        if cmd in ('F', 'set_freq'):
            return self._reply_set_freq(args, extended)
        if cmd in ('m', 'get_mode'):
            return self._reply_get_mode(extended)
        if cmd in ('M', 'set_mode'):
            return self._reply_set_mode(args, extended)
        if cmd in ('chk_vfo',):
            return "ChkVFO: 0\n"
        return "RPRT -1\n"

    def _reply_get_freq(self, extended):
        """Answer get_freq from the cached main frequency."""
        freq = self.sync.get_frequency()
        if freq is not None:
            self._last_freq = int(freq)
        if self._last_freq is None:
            return "RPRT -1\n"
        if extended:
            return f"get_freq:\nFrequency: {self._last_freq}\nRPRT 0\n"
        return f"{self._last_freq}\n"

    def _reply_set_freq(self, args, extended):
        """Forward set_freq to sync."""
        try:
            hz = int(args[0])
        except (IndexError, ValueError):
            return "RPRT -1\n"
        ok = self.sync.set_frequency(hz)
        if not ok:
            return "RPRT -1\n"
        self._last_freq = hz
        if extended:
            return f"set_freq: {hz}\nRPRT 0\n"
        return "RPRT 0\n"

    def _reply_get_mode(self, extended):
        """Answer get_mode from the held mode (sync does not track rig mode)."""
        if extended:
            return f"get_mode:\nMode: {self._mode}\nPassband: {self._passband}\nRPRT 0\n"
        return f"{self._mode}\n{self._passband}\n"

    def _reply_set_mode(self, args, extended):
        """Store mode locally (not applied to the rig)."""
        if not args:
            return "RPRT -1\n"
        self._mode = args[0]
        if len(args) > 1:
            try:
                self._passband = int(args[1])
            except ValueError:
                pass
        if extended:
            return f"set_mode: {self._mode} {self._passband}\nRPRT 0\n"
        return "RPRT 0\n"
