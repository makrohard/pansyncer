import socket
import threading

from pansyncer.config import Config
from pansyncer.rigcheck import RigChecker


class FakeDisplay:
    def __init__(self):
        self.rig_con_states = []

    def set_rig_con(self, state):
        self.rig_con_states.append(state)


class FakeRigctldServer:
    def __init__(self, *, response=b"14200000\n"):
        self.response = response
        self.commands = []
        self.host = "127.0.0.1"
        self.port = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread = None
        self._listen_sock = None

    def start(self):
        self._listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listen_sock.bind((self.host, 0))
        self._listen_sock.listen(5)
        self._listen_sock.settimeout(0.05)
        self.port = self._listen_sock.getsockname()[1]

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=1.0)
        return self

    def stop(self):
        self._stop.set()

        try:
            if self._listen_sock is not None:
                self._listen_sock.close()
        except OSError:
            pass

        if self.port is not None:
            try:
                with socket.create_connection((self.host, self.port), timeout=0.05):
                    pass
            except OSError:
                pass

        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _run(self):
        self._ready.set()

        try:
            while not self._stop.is_set():
                try:
                    conn, _ = self._listen_sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break

                with conn:
                    conn.settimeout(0.05)
                    self._handle_connection(conn)
        finally:
            try:
                if self._listen_sock is not None:
                    self._listen_sock.close()
            except OSError:
                pass

    def _handle_connection(self, conn):
        buf = bytearray()

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

            if b"\n" in buf:
                raw, _, _ = buf.partition(b"\n")
                command = raw.decode("ascii", errors="replace").strip()
                self.commands.append(command)
                conn.sendall(self.response)
                return


def make_cfg(host="127.0.0.1"):
    cfg = Config()
    cfg.main.daemon = True
    cfg.rigcheck.hamlib_remote_ip = host
    return cfg


def unused_local_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def test_is_port_open_returns_true_for_listening_server():
    server = FakeRigctldServer().start()

    try:
        checker = RigChecker(
            make_cfg(server.host),
            port=server.port,
            display=None,
            auto_start=False,
        )

        assert checker._is_port_open() is True
    finally:
        checker.cleanup()
        server.stop()


def test_is_port_open_returns_false_for_unused_port():
    port = unused_local_port()
    checker = RigChecker(
        make_cfg(),
        port=port,
        display=None,
        auto_start=False,
    )

    try:
        assert checker._is_port_open() is False
    finally:
        checker.cleanup()


def test_check_rig_accepts_integer_frequency_response():
    server = FakeRigctldServer(response=b"14200000\n").start()
    display = FakeDisplay()

    try:
        checker = RigChecker(
            make_cfg(server.host),
            port=server.port,
            display=display,
            auto_start=False,
        )

        assert checker.check_rig() is True
        assert checker.rig_freq == 14_200_000
        assert display.rig_con_states[-1] is True
        assert "f" in server.commands
    finally:
        checker.cleanup()
        server.stop()


def test_check_rig_rejects_non_integer_response():
    server = FakeRigctldServer(response=b"not-a-frequency\n").start()
    display = FakeDisplay()

    try:
        checker = RigChecker(
            make_cfg(server.host),
            port=server.port,
            display=display,
            auto_start=False,
        )

        assert checker.check_rig() is False
        assert checker.rig_freq is None
        assert display.rig_con_states[-1] is False
        assert "f" in server.commands
    finally:
        checker.cleanup()
        server.stop()


def test_check_rig_returns_false_when_server_is_unreachable():
    port = unused_local_port()
    display = FakeDisplay()
    checker = RigChecker(
        make_cfg(),
        port=port,
        display=display,
        auto_start=False,
    )

    try:
        assert checker.check_rig() is False
        assert checker.rig_freq is None
        assert display.rig_con_states[-1] is False
    finally:
        checker.cleanup()
class DummyLogger:
    def __init__(self):
        self.messages = []

    def log(self, message, level="INFO"):
        self.messages.append((level, message))


class DummyDisplay:
    def __init__(self):
        self.rig_states = []

    def set_rig_con(self, connected):
        self.rig_states.append(connected)


class DummySocket:
    def __init__(self, recv_data=b"14200000\n", fail_send=False, fail_recv=False):
        self.recv_data = recv_data
        self.fail_send = fail_send
        self.fail_recv = fail_recv
        self.closed = False
        self.sent = []

    def sendall(self, data):
        if self.fail_send:
            raise BrokenPipeError("broken")
        self.sent.append(data)

    def recv(self, size):
        if self.fail_recv:
            raise OSError("recv failed")
        return self.recv_data

    def close(self):
        self.closed = True


def make_checker(auto_start=True, port=4532, display=None):
    cfg = Config()
    cfg.sync.rig_port = 9999
    cfg.rigcheck.hamlib_command = "rigctld -m 4 -r dummy -t 1111"

    checker = RigChecker(cfg, port=port, display=display, auto_start=auto_start)
    checker.logger = DummyLogger()
    return checker


def test_ensure_rigctld_auto_start_disabled_returns_false_when_port_closed(monkeypatch):
    checker = make_checker(auto_start=False)

    monkeypatch.setattr(checker, "_is_port_open", lambda: False)

    assert checker._ensure_rigctld() is False


def test_ensure_rigctld_uses_instance_port_when_launching(monkeypatch):
    checker = make_checker(port=7777)
    launched = {}

    monkeypatch.setattr(checker, "_is_port_open", lambda: False)

    class DummyProcess:
        stdout = None
        stderr = None

        def poll(self):
            return None

    def fake_popen(cmd, **kwargs):
        launched["cmd"] = cmd
        return DummyProcess()

    monkeypatch.setattr("pansyncer.rigcheck.subprocess.Popen", fake_popen)

    assert checker._ensure_rigctld() is True
    assert "-t" in launched["cmd"]
    port_index = launched["cmd"].index("-t") + 1
    assert launched["cmd"][port_index] == "7777"


def test_stream_reader_ignores_none_stream():
    checker = make_checker()

    checker._stream_reader(None, is_error=False)

    assert checker.logger.messages == []


def test_reset_socket_clears_rig_freq_and_closes_socket():
    display = DummyDisplay()
    checker = make_checker(display=display)
    sock = DummySocket()
    checker._sock = sock
    checker.rig_freq = 14_200_000

    checker._reset_socket()

    assert checker.rig_freq is None
    assert checker._sock is None
    assert sock.closed is True
    assert display.rig_states[-1] is False


def test_check_rig_invalid_reply_clears_stale_rig_freq(monkeypatch):
    display = DummyDisplay()
    checker = make_checker(display=display)
    checker.rig_freq = 14_200_000
    checker._sock = DummySocket(recv_data=b"not-a-frequency\n")

    monkeypatch.setattr(checker, "_ensure_rigctld", lambda: True)
    monkeypatch.setattr(checker, "_ensure_socket", lambda: None)

    assert checker.check_rig() is False
    assert checker.rig_freq is None
    assert display.rig_states[-1] is False


def test_check_rig_recv_error_clears_stale_rig_freq(monkeypatch):
    display = DummyDisplay()
    checker = make_checker(display=display)
    checker.rig_freq = 14_200_000
    checker._sock = DummySocket(fail_recv=True)

    monkeypatch.setattr(checker, "_ensure_rigctld", lambda: True)
    monkeypatch.setattr(checker, "_ensure_socket", lambda: None)

    assert checker.check_rig() is False
    assert checker.rig_freq is None
    assert display.rig_states[-1] is False