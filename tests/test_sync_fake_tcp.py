import socket
import threading
import time

from pansyncer.config import Config
from pansyncer.device_register import DeviceRegister
from pansyncer.step import StepController
from pansyncer.sync import SyncManager


class FakeCatServer:
    def __init__(self, *, freq=None, lo=None, fail_sets=False, ignore_sets=False, drop_connections=0):
        self.freq = freq
        self.lo = lo
        self.fail_sets = fail_sets
        self.ignore_sets = ignore_sets
        self.drop_connections = drop_connections
        self.connections = 0
        self.commands = []
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread = None
        self._listen_sock = None
        self.host = "127.0.0.1"
        self.port = None

    def start(self):
        self._listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listen_sock.bind((self.host, 0))
        self._listen_sock.listen(1)
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

        # Unblock accept() on platforms where closing from another thread is not enough.
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

                self.connections += 1

                if self.connections <= self.drop_connections:
                    try:
                        conn.close()
                    except OSError:
                        pass
                    continue

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

            while b"\n" in buf:
                raw, _, rest = buf.partition(b"\n")
                buf = bytearray(rest)
                line = raw.decode("ascii", errors="replace").strip()
                if not line:
                    continue

                self.commands.append(line)
                response = self._handle_command(line)
                if response is not None:
                    conn.sendall(response)

    def _handle_command(self, line):
        if line == "f":
            return f"{self.freq}\n".encode("ascii")

        if line.startswith("F "):
            if self.ignore_sets:
                return None
            if self.fail_sets:
                return b"RPRT -1\n"
            self.freq = int(line.split(" ", 1)[1])
            return b"RPRT 0\n"

        if line == "LNB_LO":
            return f"{self.lo}\n".encode("ascii")

        if line.startswith("LNB_LO "):
            if self.ignore_sets:
                return None
            if self.fail_sets:
                return b"RPRT -1\n"
            self.lo = int(line.split(" ", 1)[1])
            return b"RPRT 0\n"

        return b"RPRT -1\n"


def make_sync_with_fake_servers(rig_server, gqrx_server, *, ifreq=None):
    cfg = Config()
    cfg.main.daemon = True
    cfg.main.ifreq = ifreq
    cfg.devices.enabled = ["rig", "gqrx"]

    cfg.sync.rig_host = rig_server.host
    cfg.sync.rig_port = rig_server.port
    cfg.sync.gqrx_host = gqrx_server.host
    cfg.sync.gqrx_port = gqrx_server.port

    cfg.sync.rig_socket_recon_interval = 0.0
    cfg.sync.gqrx_socket_recon_interval = 0.0
    cfg.sync.rig_freq_query_interval = 0.0
    cfg.sync.gqrx_freq_query_interval = 0.0
    cfg.sync.rig_timeout = 0.2
    cfg.sync.gqrx_timeout = 0.2

    devices = DeviceRegister(cfg)
    step = StepController()
    return SyncManager(cfg, devices, step, display=None)


def run_until(sync, predicate, *, max_ticks=500):
    now = 10.0

    for _ in range(max_ticks):
        sync.tick(now)
        if predicate():
            return
        now += 0.01
        time.sleep(0.001)

    raise AssertionError("condition was not reached")

def count_commands(server, command):
    return sum(1 for item in server.commands if item == command)

def test_fake_tcp_direct_rig_frequency_propagates_to_gqrx():
    rig = FakeCatServer(freq=14_200_000).start()
    gqrx = FakeCatServer(freq=14_125_000).start()

    try:
        sync = make_sync_with_fake_servers(rig, gqrx)

        run_until(sync, lambda: gqrx.freq == 14_200_000)

        assert "f" in rig.commands
        assert "f" in gqrx.commands
        assert "F 14200000" in gqrx.commands
        assert rig.freq == 14_200_000
        assert gqrx.freq == 14_200_000
    finally:
        try:
            sync.shutdown()
        except UnboundLocalError:
            pass
        rig.stop()
        gqrx.stop()


def test_fake_tcp_ifreq_rig_frequency_sets_gqrx_lnb_lo():
    rig = FakeCatServer(freq=14_200_000).start()
    gqrx = FakeCatServer(lo=-58_970_000).start()

    try:
        sync = make_sync_with_fake_servers(rig, gqrx, ifreq=73.095)

        run_until(sync, lambda: gqrx.lo == -58_895_000)

        assert "f" in rig.commands
        assert "LNB_LO" in gqrx.commands
        assert "LNB_LO -58895000" in gqrx.commands
        assert rig.freq == 14_200_000
        assert gqrx.lo == -58_895_000
    finally:
        try:
            sync.shutdown()
        except UnboundLocalError:
            pass
        rig.stop()
        gqrx.stop()

def test_fake_tcp_direct_rprt_error_does_not_update_gqrx_and_retries():
    rig = FakeCatServer(freq=14_200_000).start()
    gqrx = FakeCatServer(freq=14_125_000, fail_sets=True).start()

    try:
        sync = make_sync_with_fake_servers(rig, gqrx)

        run_until(sync, lambda: count_commands(gqrx, "F 14200000") >= 2)

        assert "f" in rig.commands
        assert "f" in gqrx.commands
        assert count_commands(gqrx, "F 14200000") >= 2
        assert rig.freq == 14_200_000
        assert gqrx.freq == 14_125_000
    finally:
        sync.shutdown()
        rig.stop()
        gqrx.stop()


def test_fake_tcp_direct_set_timeout_retries_after_busy_timeout():
    rig = FakeCatServer(freq=14_200_000).start()
    gqrx = FakeCatServer(freq=14_125_000, ignore_sets=True).start()

    try:
        sync = make_sync_with_fake_servers(rig, gqrx)

        run_until(sync, lambda: count_commands(gqrx, "F 14200000") >= 2, max_ticks=1000)

        assert "f" in rig.commands
        assert "f" in gqrx.commands
        assert count_commands(gqrx, "F 14200000") >= 2
        assert rig.freq == 14_200_000
        assert gqrx.freq == 14_125_000
    finally:
        sync.shutdown()
        rig.stop()
        gqrx.stop()

def test_fake_tcp_direct_reconnects_after_gqrx_disconnect_before_sync():
    rig = FakeCatServer(freq=14_200_000).start()
    gqrx = FakeCatServer(freq=14_125_000, drop_connections=1).start()

    try:
        sync = make_sync_with_fake_servers(rig, gqrx)

        run_until(
            sync,
            lambda: gqrx.connections >= 2 and gqrx.freq == 14_200_000,
            max_ticks=1000,
        )

        assert gqrx.connections >= 2
        assert "f" in rig.commands
        assert "f" in gqrx.commands
        assert "F 14200000" in gqrx.commands
        assert rig.freq == 14_200_000
        assert gqrx.freq == 14_200_000
    finally:
        sync.shutdown()
        rig.stop()
        gqrx.stop()


def test_fake_tcp_ifreq_reconnects_after_gqrx_disconnect_before_lnb_lo_sync():
    rig = FakeCatServer(freq=14_200_000).start()
    gqrx = FakeCatServer(lo=-58_970_000, drop_connections=1).start()

    try:
        sync = make_sync_with_fake_servers(rig, gqrx, ifreq=73.095)

        run_until(
            sync,
            lambda: gqrx.connections >= 2 and gqrx.lo == -58_895_000,
            max_ticks=1000,
        )

        assert gqrx.connections >= 2
        assert "f" in rig.commands
        assert "LNB_LO" in gqrx.commands
        assert "LNB_LO -58895000" in gqrx.commands
        assert rig.freq == 14_200_000
        assert gqrx.lo == -58_895_000
    finally:
        sync.shutdown()
        rig.stop()
        gqrx.stop()
def test_fake_tcp_direct_gqrx_frequency_propagates_to_rig_after_initial_sync():
    rig = FakeCatServer(freq=14_125_000).start()
    gqrx = FakeCatServer(freq=14_125_000).start()

    try:
        sync = make_sync_with_fake_servers(rig, gqrx)

        run_until(
            sync,
            lambda: (
                sync.radio["rig"]["freq_processed"] == 14_125_000
                and sync.radio["gqrx"]["freq_processed"] == 14_125_000
            ),
            max_ticks=1000,
        )

        gqrx.freq = 14_200_000

        run_until(sync, lambda: rig.freq == 14_200_000, max_ticks=1000)

        assert "f" in rig.commands
        assert "f" in gqrx.commands
        assert "F 14200000" in rig.commands
        assert rig.freq == 14_200_000
        assert gqrx.freq == 14_200_000
    finally:
        sync.shutdown()
        rig.stop()
        gqrx.stop()


def test_fake_tcp_ifreq_lnb_lo_rprt_error_does_not_update_gqrx_and_retries():
    rig = FakeCatServer(freq=14_200_000).start()
    gqrx = FakeCatServer(lo=-58_970_000, fail_sets=True).start()

    try:
        sync = make_sync_with_fake_servers(rig, gqrx, ifreq=73.095)

        run_until(
            sync,
            lambda: count_commands(gqrx, "LNB_LO -58895000") >= 2,
            max_ticks=1000,
        )

        assert "f" in rig.commands
        assert "LNB_LO" in gqrx.commands
        assert count_commands(gqrx, "LNB_LO -58895000") >= 2
        assert rig.freq == 14_200_000
        assert gqrx.lo == -58_970_000
    finally:
        sync.shutdown()
        rig.stop()
        gqrx.stop()


def test_fake_tcp_ifreq_lnb_lo_timeout_retries_after_busy_timeout():
    rig = FakeCatServer(freq=14_200_000).start()
    gqrx = FakeCatServer(lo=-58_970_000, ignore_sets=True).start()

    try:
        sync = make_sync_with_fake_servers(rig, gqrx, ifreq=73.095)

        run_until(
            sync,
            lambda: count_commands(gqrx, "LNB_LO -58895000") >= 2,
            max_ticks=1000,
        )

        assert "f" in rig.commands
        assert "LNB_LO" in gqrx.commands
        assert count_commands(gqrx, "LNB_LO -58895000") >= 2
        assert rig.freq == 14_200_000
        assert gqrx.lo == -58_970_000
    finally:
        sync.shutdown()
        rig.stop()
        gqrx.stop()


def test_fake_tcp_invalid_rig_frequency_response_does_not_sync_to_gqrx():
    rig = FakeCatServer(freq="not-a-frequency").start()
    gqrx = FakeCatServer(freq=14_125_000).start()

    try:
        sync = make_sync_with_fake_servers(rig, gqrx)

        run_until(
            sync,
            lambda: count_commands(rig, "f") >= 2 and count_commands(gqrx, "f") >= 1,
            max_ticks=1000,
        )

        assert sync.radio["rig"]["freq_cur"] is None
        assert gqrx.freq == 14_125_000
        assert all(not command.startswith("F ") for command in gqrx.commands)
    finally:
        sync.shutdown()
        rig.stop()
        gqrx.stop()