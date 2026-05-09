"""
PanSyncer radio test lab. Provides fake rigctld and fake Gqrx TCP endpoints and a control socket for manual tests.
"""

import argparse
import random
import socket
import threading
import time
from collections import deque
from contextlib import suppress

DEFAULT_NUDGE_HZ = 100
CAT_EVENT_LIMIT = 1000


def fmt_hz(value):
    if value is None:
        return "n/a"
    return f"{int(value):,}".replace(",", ".") + " Hz"


def parse_hz_arg(args, default=DEFAULT_NUDGE_HZ):
    if not args:
        return default
    return int(args[0])


class CatEventLog:
    def __init__(self, limit=CAT_EVENT_LIMIT):
        self._events = deque(maxlen=limit)
        self._seq = 0
        self._cond = threading.Condition()

    def add(self, role, direction, text):
        text = str(text).strip()
        ts = time.strftime("%H:%M:%S", time.localtime())

        with self._cond:
            self._seq += 1
            self._events.append((self._seq, ts, role, direction, text))
            self._cond.notify_all()

    def current_seq(self):
        with self._cond:
            return self._seq

    def wait_after(self, after_seq, timeout=0.2):
        with self._cond:
            if self._seq <= after_seq:
                self._cond.wait(timeout)

            events = [event for event in self._events if event[0] > after_seq]
            return events, self._seq


class FakeEndpoint:
    def __init__(self, *, name, host, port, freq_hz=0, cat_log=None):
        self.name = name
        self.role = name.lower()
        self.host = host
        self.port = port
        self.freq_hz = int(freq_hz)
        self.cat_log = cat_log

        self.delay = 0.0
        self.invalid_response = False
        self.silent_response = False
        self.rprt_error_response = False

        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._listen_sock = None
        self._thread = None
        self._clients = set()
        self._spin_stop = threading.Event()
        self._spin_thread = None
        self._spin_mode = None

    def start(self):
        with self._lock:
            if self.is_running():
                return f"{self.name}: already up\n"

            self._stop.clear()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            with suppress(OSError):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

            sock.bind((self.host, self.port))
            sock.listen(20)
            sock.settimeout(0.2)

            self._listen_sock = sock
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

        return f"{self.name}: up on {self.host}:{self.port}\n"

    def stop(self):
        self.spin_stop()

        with self._lock:
            self._stop.set()

            sock = self._listen_sock
            self._listen_sock = None
            if sock is not None:
                with suppress(OSError):
                    sock.close()

            clients = list(self._clients)

        for client in clients:
            with suppress(OSError):
                client.shutdown(socket.SHUT_RDWR)
            with suppress(OSError):
                client.close()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)

        with self._lock:
            self._thread = None
            self._clients.clear()

        return f"{self.name}: down\n"

    def restart(self):
        msg = self.stop()
        time.sleep(0.3)
        msg += self.start()
        return msg

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def client_count(self):
        with self._lock:
            return len(self._clients)

    def set_freq(self, freq_hz):
        with self._lock:
            self.freq_hz = int(freq_hz)
            freq = self.freq_hz
        return f"{self.name}: freq={freq}\n"

    def nudge(self, delta_hz):
        with self._lock:
            self.freq_hz += int(delta_hz)
            freq = self.freq_hz
        return f"{self.name}: freq={freq}\n"

    def set_delay(self, seconds):
        with self._lock:
            self.delay = max(0.0, float(seconds))
            delay = self.delay
        return f"{self.name}: delay={delay:.3f}s\n"

    def set_response_mode(self, mode):
        mode = mode.lower()
        valid_modes = {"valid", "invalid", "silent", "rprt-error"}
        if mode not in valid_modes:
            raise ValueError(f"expected one of: {', '.join(sorted(valid_modes))}")

        with self._lock:
            self.invalid_response = mode == "invalid"
            self.silent_response = mode == "silent"
            self.rprt_error_response = mode == "rprt-error"

        return f"{self.name}: mode={mode}\n"

    def response_mode(self):
        with self._lock:
            if self.silent_response:
                return "silent"
            if self.rprt_error_response:
                return "rprt-error"
            if self.invalid_response:
                return "invalid"
            return "valid"

    def spin_status(self):
        with self._lock:
            if self._spin_thread is not None and self._spin_thread.is_alive():
                return self._spin_mode or "on"
            return "off"

    def spin_start(self, mode="start"):
        mode = mode.lower()
        if mode not in ("start", "fast"):
            raise ValueError("expected start|fast")

        self.spin_stop()
        self.set_response_mode("valid")

        with self._lock:
            self._spin_stop.clear()
            self._spin_mode = mode
            self._spin_thread = threading.Thread(target=self._spin_loop, args=(mode,), daemon=True)
            self._spin_thread.start()

        return f"{self.name}: spin={mode}\n"

    def spin_stop(self):
        with self._lock:
            thread = self._spin_thread
            self._spin_stop.set()

        if thread is not None:
            thread.join(timeout=1.0)

        with self._lock:
            if self._spin_thread is thread:
                self._spin_thread = None
            self._spin_mode = None

        return f"{self.name}: spin=off\n"

    def _spin_loop(self, mode):
        try:
            while not self._spin_stop.is_set():
                direction = random.choice((-1, 1))

                if mode == "fast":
                    run_seconds = random.uniform(0.2, 0.8)
                    interval = random.uniform(0.0005, 0.005)
                    step_hz = random.choice((100, 200, 500))
                else:
                    run_seconds = random.uniform(1.5, 5.0)
                    interval = random.uniform(0.04, 0.35)
                    step_hz = random.choice((10, 20, 30, 40, 50, 100, 200))

                end_time = time.monotonic() + run_seconds
                while time.monotonic() < end_time and not self._spin_stop.is_set():
                    with self._lock:
                        self.freq_hz += direction * step_hz
                    time.sleep(interval)
        finally:
            with self._lock:
                self._spin_thread = None
                self._spin_mode = None
                self._spin_stop.set()

    def status_lines(self):
        with self._lock:
            freq = self.freq_hz
            delay = self.delay

        return [
            f"{self.name}:",
            f"  server:          {'UP' if self.is_running() else 'DOWN'}",
            f"  cat freq/f:      {fmt_hz(freq)}",
            f"  response mode:   {self.response_mode()}",
            f"  spin:            {self.spin_status()}",
            f"  clients:         {self.client_count()}",
            f"  delay:           {delay:.3f} s",
        ]

    def _cat_event(self, direction, text):
        if self.cat_log is not None:
            self.cat_log.add(self.role, direction, text)

    def _run(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._listen_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            with self._lock:
                self._clients.add(conn)

            thread = threading.Thread(target=self._handle_client, args=(conn,), daemon=True)
            thread.start()

    def _handle_client(self, conn):
        buf = bytearray()
        conn.settimeout(0.2)

        try:
            while not self._stop.is_set():
                try:
                    data = conn.recv(1024)
                except socket.timeout:
                    continue
                except OSError:
                    return

                if not data:
                    return

                buf.extend(data)

                while b"\n" in buf:
                    raw, _, rest = buf.partition(b"\n")
                    buf = bytearray(rest)

                    line = raw.decode("ascii", errors="replace").strip()
                    if not line:
                        continue

                    self._cat_event("RX", line)

                    response = self._handle_command(line)
                    if response is None:
                        self._cat_event("TX", "<silent>")
                        continue

                    try:
                        conn.sendall(response)
                    except OSError:
                        return

                    self._cat_event("TX", response.decode("ascii", errors="replace").strip())

        finally:
            with self._lock:
                self._clients.discard(conn)
            with suppress(OSError):
                conn.close()

    def _common_read_response(self, value):
        with self._lock:
            reply_value = int(value)
            delay = self.delay
            silent = self.silent_response
            rprt_error = self.rprt_error_response
            invalid = self.invalid_response

        if delay > 0:
            time.sleep(delay)
        if silent:
            return None
        if rprt_error:
            return b"RPRT -1\n"
        if invalid:
            return b"not-a-frequency\n"
        return f"{reply_value}\n".encode("ascii")

    def _common_write_response(self, setter, value):
        with self._lock:
            delay = self.delay
            silent = self.silent_response
            rprt_error = self.rprt_error_response

        if delay > 0:
            time.sleep(delay)
        if silent:
            return None
        if rprt_error:
            return b"RPRT -1\n"

        setter(value)
        return b"RPRT 0\n"

    def _handle_command(self, line):
        raise NotImplementedError


class FakeRig(FakeEndpoint):
    def __init__(self, *, host, port, freq_hz, cat_log=None):
        super().__init__(name="Rig", host=host, port=port, freq_hz=freq_hz, cat_log=cat_log)

    def _handle_command(self, line):
        if line == "f":
            with self._lock:
                freq = self.freq_hz
            return self._common_read_response(freq)

        if line.startswith("F "):
            try:
                freq = int(line.split(" ", 1)[1])
            except ValueError:
                return b"RPRT -1\n"
            return self._common_write_response(self.set_freq, freq)

        return b"RPRT -1\n"


class FakeGqrx(FakeEndpoint):
    def __init__(self, *, host, port, freq_hz, lnb_lo_hz, ifreq_hz=None, cat_log=None):
        super().__init__(name="Gqrx", host=host, port=port, freq_hz=freq_hz, cat_log=cat_log)
        self.lnb_lo_hz = int(lnb_lo_hz)
        self.ifreq_hz = ifreq_hz

    def set_lo(self, lo_hz):
        with self._lock:
            self.lnb_lo_hz = int(lo_hz)
            lo = self.lnb_lo_hz
        return f"Gqrx: lnb_lo={lo}\n"

    def status_lines(self):
        lines = super().status_lines()
        with self._lock:
            lo = self.lnb_lo_hz
            ifreq = self.ifreq_hz

        lines.insert(2, f"  lnb_lo:         {fmt_hz(lo)}")
        if ifreq is not None:
            lines.insert(3, f"  ifreq view:     {fmt_hz(lo + ifreq)}")
        else:
            lines.insert(3, "  ifreq view:     n/a")
        return lines

    def _handle_command(self, line):
        if line == "f":
            with self._lock:
                freq = self.freq_hz
            return self._common_read_response(freq)

        if line.startswith("F "):
            try:
                freq = int(line.split(" ", 1)[1])
            except ValueError:
                return b"RPRT -1\n"
            return self._common_write_response(self.set_freq, freq)

        if line == "LNB_LO":
            with self._lock:
                lo = self.lnb_lo_hz
            return self._common_read_response(lo)

        if line.startswith("LNB_LO "):
            try:
                lo = int(line.split(" ", 1)[1])
            except ValueError:
                return b"RPRT -1\n"
            return self._common_write_response(self.set_lo, lo)

        return b"RPRT -1\n"


class ControlServer:
    def __init__(self, *, host, port, rig, gqrx, cat_log, stop_event):
        self.host = host
        self.port = port
        self.rig = rig
        self.gqrx = gqrx
        self.cat_log = cat_log
        self.stop_event = stop_event

        self._stop = threading.Event()
        self._listen_sock = None
        self._thread = None

    def start(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        with suppress(OSError):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

        sock.bind((self.host, self.port))
        sock.listen(5)
        sock.settimeout(0.2)

        self._listen_sock = sock
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

        print(f"Control: up on {self.host}:{self.port}", flush=True)

    def stop(self):
        self._stop.set()
        sock = self._listen_sock
        self._listen_sock = None
        if sock is not None:
            with suppress(OSError):
                sock.close()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _run(self):
        while not self._stop.is_set() and not self.stop_event.is_set():
            try:
                conn, _ = self._listen_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            thread = threading.Thread(target=self._handle_client, args=(conn,), daemon=True)
            thread.start()

    def _send(self, conn, text):
        conn.sendall(text.encode("utf-8"))

    def _handle_client(self, conn):
        buf = bytearray()

        with conn:
            self._send(conn, "PanSyncer testlab control. Type 'help'.\n")
            self._send(conn, "testlab> ")

            while not self.stop_event.is_set():
                try:
                    data = conn.recv(1024)
                except OSError:
                    return

                if not data:
                    return

                buf.extend(data)

                while b"\n" in buf:
                    raw, _, rest = buf.partition(b"\n")
                    buf = bytearray(rest)

                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        self._send(conn, "testlab> ")
                        continue

                    parts = line.split()
                    if parts and parts[0].lower() in ("watch"):
                        try:
                            close_connection = self._watch(conn, parts[1:])
                        except Exception as exc:
                            self._send(conn, f"error: {exc}\n")
                            close_connection = False

                        if close_connection:
                            return

                        self._send(conn, "testlab> ")
                        continue

                    try:
                        result, close_connection = self._dispatch(line)
                    except Exception as exc:
                        result = f"error: {exc}\n"
                        close_connection = False

                    self._send(conn, result)

                    if close_connection:
                        return

                    self._send(conn, "testlab> ")

    def _parse_watch_roles(self, args):
        if not args:
            return {"rig", "gqrx"}

        target = args[0].lower()
        if target in ("all", "both"):
            return {"rig", "gqrx"}
        if target in ("rig", "gqrx"):
            return {target}

        raise ValueError("expected watch rig|gqrx|all")

    def _watch(self, conn, args):
        roles = self._parse_watch_roles(args)
        last_seq = self.cat_log.current_seq()
        old_timeout = conn.gettimeout()
        buf = bytearray()

        role_text = "all" if roles == {"rig", "gqrx"} else next(iter(roles))
        self._send(conn, f"watching CAT commands for {role_text}; type 'q' to return\n")

        try:
            conn.settimeout(0.2)

            while not self.stop_event.is_set():
                events, last_seq = self.cat_log.wait_after(last_seq, timeout=0.2)

                for _, ts, role, direction, text in events:
                    if role in roles:
                        self._send(conn, f"{ts} {role.upper():4} {direction:<2} {text}\n")

                try:
                    data = conn.recv(1024)
                except socket.timeout:
                    continue
                except OSError:
                    return True

                if not data:
                    return True

                buf.extend(data)

                while b"\n" in buf:
                    raw, _, rest = buf.partition(b"\n")
                    buf = bytearray(rest)

                    line = raw.decode("utf-8", errors="replace").strip().lower()
                    if not line:
                        continue

                    if line == "q":
                        return False

                    if line == "shutdown":
                        self.stop_event.set()
                        self._send(conn, "shutting down testlab\n")
                        return True

                    self._send(conn, "watch mode: type 'q' to return\n")

            return True

        finally:
            conn.settimeout(old_timeout)

    def _dispatch(self, line):
        parts = line.split()
        command = parts[0].lower()
        args = parts[1:]

        if command == "help":
            return self._help(), False

        if command == "status":
            return self._status(), False

        if command == "shutdown":
            self.stop_event.set()
            return "shutting down testlab\n", True

        if command == "rig":
            return self._handle_endpoint(self.rig, args, allow_lo=False), False

        if command == "gqrx":
            return self._handle_endpoint(self.gqrx, args, allow_lo=True), False

        return "unknown command; type 'help'\n", False

    def _require_arg(self, endpoint, action, rest, expected):
        if not rest:
            raise ValueError(f"{endpoint.name.lower()} {action}: missing argument, expected {expected}")
        return rest[0]

    def _handle_endpoint(self, endpoint, args, *, allow_lo):
        if not args:
            raise ValueError(f"{endpoint.name.lower()}: missing action")

        action = args[0].lower()
        rest = args[1:]

        if action == "up":
            return endpoint.start()

        if action == "down":
            return endpoint.stop()

        if action == "restart":
            return endpoint.restart()

        if action == "freq":
            value = self._require_arg(endpoint, action, rest, "<hz>")
            return endpoint.set_freq(int(value))

        if action == "nudge":
            return endpoint.nudge(parse_hz_arg(rest, DEFAULT_NUDGE_HZ))

        if action == "delay":
            value = self._require_arg(endpoint, action, rest, "<seconds>")
            return endpoint.set_delay(float(value))

        if action == "mode":
            value = self._require_arg(endpoint, action, rest, "valid|invalid|silent|rprt-error")
            return endpoint.set_response_mode(value)

        if action == "spin":
            value = self._require_arg(endpoint, action, rest, "start|fast|stop|status").lower()
            if value == "start":
                return endpoint.spin_start("start")
            if value == "fast":
                return endpoint.spin_start("fast")
            if value == "stop":
                return endpoint.spin_stop()
            if value == "status":
                return f"{endpoint.name}: spin={endpoint.spin_status()}\n"
            raise ValueError(f"{endpoint.name.lower()} spin: expected start|fast|stop|status")

        if allow_lo and action == "lo":
            value = self._require_arg(endpoint, action, rest, "<hz>")
            return endpoint.set_lo(int(value))

        raise ValueError(f"{endpoint.name.lower()} {action}: unknown action")

    def _status(self):
        lines = []
        lines.extend(self.rig.status_lines())
        lines.append("")
        lines.extend(self.gqrx.status_lines())
        lines.append("")
        return "\n".join(lines)

    def _help(self):
        return """Commands:
  help
  status
  shutdown
  watch [rig|gqrx|all]
  
  rig up
  rig down
  rig restart
  rig freq <hz>
  rig nudge <hz>
  rig delay <seconds>
  rig mode valid|invalid|silent|rprt-error
  rig spin start|fast|stop|status

  gqrx up
  gqrx down
  gqrx restart
  gqrx freq <hz>
  gqrx nudge <hz>
  gqrx delay <seconds>
  gqrx mode valid|invalid|silent|rprt-error
  gqrx spin start|fast|stop|status

Debug:
  gqrx lo <hz>

Watch mode:
  watch all
  watch rig
  watch gqrx
  type q to return to the control prompt

Default nudge step: 100 Hz
"""


def parse_args():
    parser = argparse.ArgumentParser(description="PanSyncer manual test fake radio lab")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--rig-port", type=int, default=4533)
    parser.add_argument("--gqrx-port", type=int, default=7357)
    parser.add_argument("--control-port", type=int, default=4534)
    parser.add_argument("--rig-freq", type=int, default=14_200_000)
    parser.add_argument("--gqrx-freq", type=int, default=14_125_000)
    parser.add_argument("--gqrx-lo", type=int, default=-58_970_000)
    parser.add_argument("--ifreq", type=float, default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    ifreq_hz = int(round(abs(args.ifreq * 1_000_000))) if args.ifreq is not None else None
    stop_event = threading.Event()
    cat_log = CatEventLog()

    rig = FakeRig(
        host=args.host,
        port=args.rig_port,
        freq_hz=args.rig_freq,
        cat_log=cat_log,
    )
    gqrx = FakeGqrx(
        host=args.host,
        port=args.gqrx_port,
        freq_hz=args.gqrx_freq,
        lnb_lo_hz=args.gqrx_lo,
        ifreq_hz=ifreq_hz,
        cat_log=cat_log,
    )

    control = ControlServer(
        host=args.host,
        port=args.control_port,
        rig=rig,
        gqrx=gqrx,
        cat_log=cat_log,
        stop_event=stop_event,
    )

    try:
        print(rig.start(), end="")
        print(gqrx.start(), end="")
        control.start()

        print()
        print("Control:")
        print(f"  rlwrap nc {args.host} {args.control_port}")
        print()
        print("PanSyncer direct mode:")
        print(
            "  python -m pansyncer.main "
            f"--no-auto-rig --rig-port {args.rig_port} --gqrx-port {args.gqrx_port}"
        )
        print()
        print("PanSyncer iFreq mode:")
        print(
            "  python -m pansyncer.main "
            f"--no-auto-rig --rig-port {args.rig_port} --gqrx-port {args.gqrx_port} --ifreq 73.095"
        )
        print()
        print("Press Ctrl-C or use 'shutdown' on the control socket.")

        while not stop_event.is_set():
            time.sleep(0.2)

    except KeyboardInterrupt:
        pass
    finally:
        control.stop()
        print(rig.stop(), end="")
        print(gqrx.stop(), end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())