from pansyncer.config import Config
from pansyncer.device_register import DeviceRegister
from pansyncer.step import StepController
from pansyncer.sync import SyncManager


class DummySocket:
    def __init__(self, recv_chunks=()):
        self.sent = []
        self.recv_chunks = list(recv_chunks)
        self.closed = False

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, size):
        if not self.recv_chunks:
            return b""
        return self.recv_chunks.pop(0)

    def close(self):
        self.closed = True

    def fileno(self):
        return 999999


def make_sync(enabled=("rig", "gqrx"), ifreq=None):
    cfg = Config()
    cfg.main.daemon = True
    cfg.main.ifreq = ifreq
    cfg.devices.enabled = list(enabled)

    devices = DeviceRegister(cfg)
    step = StepController()
    return SyncManager(cfg, devices, step, display=None)


def connect_radio(sync, role, freq_cur, sock=None, freq_processed=None):
    sock = sock or DummySocket()
    sync.radio[role].update(
        {
            "sock": sock,
            "connected": True,
            "freq_cur": freq_cur,
            "freq_processed": freq_cur if freq_processed is None else freq_processed,
            "freq_sent": None,
            "freq_queued": None,
            "freq_queued_is_lo": False,
            "query": None,
            "is_busy": None,
            "recv_buf": bytearray(),
            "send_timestamp": 0.0,
        }
    )
    return sock


def test_send_query_sends_frequency_set_and_marks_busy():
    sync = make_sync()
    sock = connect_radio(sync, "rig", 14_125_000)

    assert sync._queue_set("rig", 14_200_000) is True
    sync._send_query("rig", now=10.0)

    assert sock.sent == [b"F 14200000\n"]
    assert sync.radio["rig"]["freq_sent"] == 14_200_000
    assert sync.radio["rig"]["freq_queued"] is None
    assert sync.radio["rig"]["freq_queued_is_lo"] is False
    assert sync.radio["rig"]["query"] is None
    assert sync.radio["rig"]["is_busy"] == 10.0
    assert sync.radio["rig"]["send_timestamp"] == 10.0


def test_send_query_sends_lnb_lo_set_and_marks_busy():
    sync = make_sync(ifreq=73.095)
    sock = connect_radio(sync, "gqrx", -58_970_000)

    assert sync._queue_set("gqrx", -58_895_000, is_lo=True) is True
    sync._send_query("gqrx", now=10.0)

    assert sock.sent == [b"LNB_LO -58895000\n"]
    assert sync.radio["gqrx"]["freq_sent"] == -58_895_000
    assert sync.radio["gqrx"]["freq_queued"] is None
    assert sync.radio["gqrx"]["freq_queued_is_lo"] is False
    assert sync.radio["gqrx"]["query"] is None
    assert sync.radio["gqrx"]["is_busy"] == 10.0
    assert sync.radio["gqrx"]["send_timestamp"] == 10.0


def test_process_rprt_success_updates_current_frequency_and_clears_busy():
    sync = make_sync()
    sock = DummySocket([b"RPRT 0\n"])
    connect_radio(sync, "rig", 14_125_000, sock=sock)

    sync.radio["rig"]["freq_sent"] = 14_200_000
    sync.radio["rig"]["is_busy"] = 10.0

    sync._process_incoming("rig", now=10.1)

    assert sync.radio["rig"]["freq_cur"] == 14_200_000
    assert sync.radio["rig"]["freq_sent"] is None
    assert sync.radio["rig"]["is_busy"] is None
    assert sync.radio["rig"]["recv_buf"] == bytearray()


def test_process_frequency_reply_updates_current_frequency_and_clears_busy():
    sync = make_sync()
    sock = DummySocket([b"14200000\n"])
    connect_radio(sync, "rig", 14_125_000, sock=sock)

    sync.radio["rig"]["is_busy"] = 10.0

    sync._process_incoming("rig", now=10.1)

    assert sync.radio["rig"]["freq_cur"] == 14_200_000
    assert sync.radio["rig"]["freq_sent"] is None
    assert sync.radio["rig"]["is_busy"] is None
    assert sync.radio["rig"]["recv_buf"] == bytearray()


def test_process_partial_response_keeps_buffer_and_busy_until_complete():
    sync = make_sync()
    sock = DummySocket([b"1420", b"0000\n"])
    connect_radio(sync, "rig", 14_125_000, sock=sock)

    sync.radio["rig"]["is_busy"] = 10.0

    sync._process_incoming("rig", now=10.1)

    assert sync.radio["rig"]["freq_cur"] == 14_125_000
    assert sync.radio["rig"]["is_busy"] == 10.0
    assert sync.radio["rig"]["recv_buf"] == bytearray(b"1420")

    sync._process_incoming("rig", now=10.2)

    assert sync.radio["rig"]["freq_cur"] == 14_200_000
    assert sync.radio["rig"]["is_busy"] is None
    assert sync.radio["rig"]["recv_buf"] == bytearray()


def test_process_rprt_error_clears_sent_and_rolls_processed_back():
    sync = make_sync()
    sock = DummySocket([b"RPRT -1\n"])
    connect_radio(sync, "rig", 14_125_000, sock=sock)

    sync.radio["rig"]["freq_sent"] = 14_200_000
    sync.radio["rig"]["freq_processed"] = 14_200_000
    sync.radio["rig"]["is_busy"] = 10.0

    sync._process_incoming("rig", now=10.1)

    assert sync.radio["rig"]["freq_cur"] == 14_125_000
    assert sync.radio["rig"]["freq_sent"] is None
    assert sync.radio["rig"]["freq_processed"] == 14_125_000
    assert sync.radio["rig"]["is_busy"] is None


def test_freq_check_timeout_clears_busy_sent_and_stale_buffer():
    sync = make_sync()
    connect_radio(sync, "rig", 14_125_000)

    sync.radio["rig"]["freq_sent"] = 14_200_000
    sync.radio["rig"]["freq_processed"] = 14_200_000
    sync.radio["rig"]["is_busy"] = 10.0
    sync.radio["rig"]["recv_buf"] = bytearray(b"partial")

    sync._freq_check_timeout("rig", now=13.0)

    assert sync.radio["rig"]["freq_cur"] == 14_125_000
    assert sync.radio["rig"]["freq_sent"] is None
    assert sync.radio["rig"]["freq_processed"] == 14_125_000
    assert sync.radio["rig"]["is_busy"] is None
    assert sync.radio["rig"]["recv_buf"] == bytearray()


def test_cleanup_socket_closes_socket_and_resets_socket_state():
    sync = make_sync()
    sock = connect_radio(sync, "rig", 14_125_000)

    sync.sync_on = True
    sync.radio["rig"]["freq_sent"] = 14_200_000
    sync.radio["rig"]["freq_queued"] = 14_300_000
    sync.radio["rig"]["freq_queued_is_lo"] = True
    sync.radio["rig"]["query"] = b"f\n"
    sync.radio["rig"]["is_busy"] = 10.0
    sync.radio["rig"]["recv_buf"] = bytearray(b"partial")

    sync._cleanup_socket("rig")

    assert sock.closed is True
    assert sync.radio["rig"]["sock"] is None
    assert sync.radio["rig"]["connected"] is False
    assert sync.radio["rig"]["freq_cur"] == 14_125_000
    assert sync.radio["rig"]["freq_processed"] == 14_125_000
    assert sync.radio["rig"]["freq_sent"] is None
    assert sync.radio["rig"]["freq_queued"] is None
    assert sync.radio["rig"]["freq_queued_is_lo"] is False
    assert sync.radio["rig"]["query"] is None
    assert sync.radio["rig"]["is_busy"] is None
    assert sync.radio["rig"]["recv_buf"] == bytearray()
    assert sync.sync_on is False