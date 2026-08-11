import socket
import sys
import time

from pansyncer.config import Config
from pansyncer.main import PanSyncer
from pansyncer.proxy import RigctldProxy


class FakeSync:
    def __init__(self, freq=None):
        self._freq = freq
        self.sets = []

    def get_frequency(self):
        return self._freq

    def set_frequency(self, hz, role=None):
        self.sets.append(hz)
        self._freq = hz
        return True


def make_proxy(sync, **overrides):
    cfg = Config()
    cfg.proxy.enabled = True
    cfg.proxy.port = 0
    for key, val in overrides.items():
        setattr(cfg.proxy, key, val)
    return RigctldProxy(cfg, sync)


def connect(proxy):
    return socket.create_connection((proxy.cfg.host, proxy.port), timeout=1.0)


def exchange(proxy, client, request, ticks=200):
    client.sendall(request)
    client.setblocking(False)
    now = 10.0
    for _ in range(ticks):
        proxy.tick(now)
        now += 0.01
        try:
            data = client.recv(4096)
            if data:
                return data.decode()
        except BlockingIOError:
            time.sleep(0.001)
    raise AssertionError("no reply")


def test_proxy_get_freq_returns_cached_frequency():
    proxy = make_proxy(FakeSync(freq=14_074_000))
    client = connect(proxy)
    try:
        reply = exchange(proxy, client, b"+\\get_freq\n")
        assert "Frequency: 14074000" in reply
        assert "RPRT 0" in reply
    finally:
        client.close()
        proxy.shutdown()


def test_proxy_set_freq_reaches_sync():
    sync = FakeSync(freq=14_074_000)
    proxy = make_proxy(sync)
    client = connect(proxy)
    try:
        reply = exchange(proxy, client, b"+\\set_freq 14100000\n")
        assert "RPRT 0" in reply
        assert sync.sets == [14_100_000]
    finally:
        client.close()
        proxy.shutdown()


def test_proxy_serves_last_freq_when_sync_returns_none():
    sync = FakeSync(freq=14_074_000)
    proxy = make_proxy(sync)
    client = connect(proxy)
    try:
        exchange(proxy, client, b"+\\get_freq\n")            # cache it
        sync._freq = None                                     # rig stalls
        reply = exchange(proxy, client, b"+\\get_freq\n")
        assert "Frequency: 14074000" in reply
    finally:
        client.close()
        proxy.shutdown()


def test_proxy_disabled_opens_no_socket():
    cfg = Config()
    proxy = RigctldProxy(cfg, FakeSync())                     # enabled defaults to False
    try:
        assert proxy.port is None
    finally:
        proxy.shutdown()


def test_proxy_cli_flag_enables_proxy(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["pansyncer", "--proxy", "-c", "/nonexistent.toml"])
    cfg = Config.from_args_and_file(PanSyncer.parse_args())
    assert cfg.proxy.enabled is True
