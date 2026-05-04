"""
Panadapter rigcheck.py
Launches and monitors rigctld
"""

import subprocess
import socket
import threading
import os
import signal
import re
import shlex
from dataclasses import dataclass
from typing import Optional
from pansyncer.logger import Logger

@dataclass
class RigCheckConfig:
    """Default configuration for RigChecker."""
    hamlib_command: str = "rigctld -m 4 -r 127.0.0.1:12345 -t 4532"
    hamlib_remote_ip: str = "127.0.0.1"
    log_level: str = "INFO"
    logfile_path: Optional[str] = None

class RigChecker:
    """ Starts rigctld if requested, checks Rig connectivity. """

    def __init__(self, cfg, port=4532, display=None, auto_start=True):
        self.cfg = cfg
        self.port = port
        self.display = display
        self.auto_start = auto_start
        self._proc = None
        self._sock = None
        self.rig_freq = None
        self.logger = Logger(name=__name__,
                             display=self.display,
                             level=self.cfg.rigcheck.log_level,
                             logfile_path=self.cfg.rigcheck.logfile_path)

    def check_rig(self):
        """
        Rig connectivity check. Opens a separate socket to rigctld and requests frequency.
        Integer response is interpreted as "rig alive". FLrig may respond freq, even if RIG is not connected.
        """
        self._ensure_rigctld()
        self._ensure_socket()

        if not self._sock:
            if self.display: self.display.set_rig_con(False)
            return False

        try:                                                                            # Request RIG FREQ
            self._sock.sendall(b'f\n')
            self.logger.log("RIGCHECK SENT FREQ REQUEST", "DEBUG")
        except (BrokenPipeError, ConnectionResetError, socket.error) as e:
            self.logger.log(f"RIGCHECK socket send failed: {e}", "WARNING")
            self._reset_socket()
            return False

        try:                                                                            # Read socket
            data = self._sock.recv(1024)
        except OSError as e:
            self.logger.log(f"RIGCHECK RECV ERROR {e}", "DEBUG")
            self._reset_socket()
            return False
        if not data:
            self.logger.log("RIGCHECK SOCKET DIED", "WARNING")
            self._reset_socket()
            return False

        self.logger.log(f"RIGCHECK RECEIVED: {data}", "DEBUG")

        reply = data.partition(b'\n')[0].decode().strip()
        try:
            freq = int(reply)
            self.rig_freq = freq
            if self.display: self.display.set_rig_con(True)
            return True
        except ValueError:
            if self.display: self.display.set_rig_con(False)
            return False

    def _ensure_rigctld(self):
        """ Start rigctld if it's not already listening on the configured port. """
        if getattr(self, '_proc', None) and self._proc.poll() is None:
            return
        if not self._is_port_open():
            if not self.auto_start:
                self.logger.log("rigctld not running. Auto-Start disabled. Restart rigctld manually","CRITICAL")
                return True

            self.logger.log(f"Launching rigctld on port {self.port}", "INFO")

            cmd = shlex.split(self.cfg.rigcheck.hamlib_command)                         # Hamlib command
            cmd = self._set_rigctld_port(cmd, self.cfg.sync.rig_port)                   # use actual rig port

                                                                                        # Launch rigctld
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                preexec_fn=os.setsid
            )
                                                                                        # Capture rigctld output
            threading.Thread(target=self._stream_reader, args=(self._proc.stdout, False), daemon=True).start()
            threading.Thread(target=self._stream_reader, args=(self._proc.stderr, True), daemon=True).start()

    def _is_port_open(self):
        """ Return True if rigctld is listening on the configured port. """
        try:
            con = socket.create_connection((self.cfg.rigcheck.hamlib_remote_ip, self.port), timeout=2)
            con.close()
            return True
        except OSError:
            return False

    def _stream_reader(self, stream, is_error):
        """ Read rigctl output """
        for line in iter(stream.readline, ''):
            level = "ERROR" if is_error else "INFO"
            self.logger.log(f"[{level.upper()}: RIGCTLD STREAM READER] {line.strip()}", "DEBUG")
        stream.close()

    def _ensure_socket(self):
        """ Open a socket to rigctld to query rig is alive"""
        if self._sock is None:
            try:
                self._sock = socket.create_connection((self.cfg.rigcheck.hamlib_remote_ip, self.port), timeout=2)
                self._sock.settimeout(0.5)
            except Exception as e:
                self.logger.log(f"Could not open rigctld socket: {e}", "DEBUG")
                self._sock = None

    def _reset_socket(self):
        """Close the socket."""
        if self.display: self.display.set_rig_con(False)
        if self._sock is None:
            return
        try:
            self._sock.close()
        except OSError as e:
                self.logger.log(f"RIGCHECK error closing socket: {e}", "DEBUG")
        finally:
            self._sock = None

    @staticmethod
    def _set_rigctld_port(args, port):
        """Remove rigctld TCP port options and append the configured port."""
        out = []
        skip_next = False

        for arg in args:
            if skip_next:
                skip_next = False
                continue
            if arg in ('-t', '--port'):
                skip_next = True
                continue
            if arg.startswith('-t') and len(arg) > 2:
                continue
            if arg.startswith('--port='):
                continue
            out.append(arg)
        out.extend(['-t', str(port)])
        return out

    def cleanup(self):
        """ Terminate rigctld subprocess and close socket on shutdown. """
        if self._sock:                                                                  # Close socket
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        if self._proc:                                                                  # Terminate rigctld
            self.logger.log("Stopping rigctld...", "INFO")
            pid = self._proc.pid
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
                try:
                    self._proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.logger.log("rigctld did not terminate, sending SIGKILL", "DEBUG")
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                    self._proc.wait(timeout=1)
            except Exception as e:
                self.logger.log(f"Error terminating rigctld (pid {pid}): {e}", "DEBUG")
            finally:
                for stream in (self._proc.stdout, self._proc.stderr):                   # Send EOF to kill threads
                    try:
                        if stream:
                            stream.close()
                    except Exception:
                        pass
                self._proc = None
        try:
            self.logger.close()
        except Exception:
            pass