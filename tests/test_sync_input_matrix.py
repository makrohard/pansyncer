from pansyncer.config import Config
from pansyncer.device_register import DeviceRegister
from pansyncer.step import StepController
from pansyncer.sync import SyncManager


class DummySocket:
    pass


def make_sync(enabled=("rig", "gqrx"), ifreq=None, step_value=100):
    cfg = Config()
    cfg.main.daemon = True
    cfg.main.ifreq = ifreq
    cfg.devices.enabled = list(enabled)

    devices = DeviceRegister(cfg)
    step = StepController()
    step.set_step(step_value)

    return SyncManager(cfg, devices, step, display=None)


def connect_radio(sync, role, freq_cur, freq_processed=None):
    sync.radio[role].update(
        {
            "sock": DummySocket(),
            "connected": True,
            "freq_cur": freq_cur,
            "freq_processed": freq_cur if freq_processed is None else freq_processed,
            "freq_sent": None,
            "freq_queued": None,
            "freq_queued_is_lo": False,
            "query": None,
            "is_busy": None,
        }
    )


def assert_no_queue(sync, role):
    assert sync.radio[role]["freq_queued"] is None
    assert sync.radio[role]["freq_queued_is_lo"] is False


def test_direct_rig_only_nudge_queues_frequency_to_rig():
    sync = make_sync(enabled=("rig",))
    connect_radio(sync, "rig", 14_125_000)

    sync.nudge(100)

    assert sync.radio["rig"]["freq_queued"] == 14_125_100
    assert sync.radio["rig"]["freq_queued_is_lo"] is False
    assert_no_queue(sync, "gqrx")


def test_direct_gqrx_only_nudge_queues_frequency_to_gqrx():
    sync = make_sync(enabled=("gqrx",))
    connect_radio(sync, "gqrx", 14_125_000)

    sync.nudge(100)

    assert sync.radio["gqrx"]["freq_queued"] == 14_125_100
    assert sync.radio["gqrx"]["freq_queued_is_lo"] is False
    assert_no_queue(sync, "rig")


def test_direct_rig_and_gqrx_nudge_targets_rig_first():
    sync = make_sync(enabled=("rig", "gqrx"))
    connect_radio(sync, "rig", 14_125_000)
    connect_radio(sync, "gqrx", 14_125_000)

    sync.nudge(100)

    assert sync.radio["rig"]["freq_queued"] == 14_125_100
    assert sync.radio["rig"]["freq_queued_is_lo"] is False
    assert_no_queue(sync, "gqrx")


def test_direct_rig_and_gqrx_nudge_then_sync_queues_gqrx_to_follow_rig():
    sync = make_sync(enabled=("rig", "gqrx"))
    connect_radio(sync, "rig", 14_125_000)
    connect_radio(sync, "gqrx", 14_125_000)

    sync.nudge(100)
    sync._apply_sync_actions()

    assert sync.radio["rig"]["freq_queued"] == 14_125_100
    assert sync.radio["gqrx"]["freq_queued"] == 14_125_100
    assert sync.radio["gqrx"]["freq_queued_is_lo"] is False


def test_ifreq_rig_only_nudge_queues_main_frequency_to_rig():
    sync = make_sync(enabled=("rig",), ifreq=73.095)
    connect_radio(sync, "rig", 14_125_000)

    sync.nudge(100)

    assert sync.radio["rig"]["freq_queued"] == 14_125_100
    assert sync.radio["rig"]["freq_queued_is_lo"] is False
    assert_no_queue(sync, "gqrx")


def test_ifreq_rig_and_gqrx_nudge_targets_rig_main_frequency():
    sync = make_sync(enabled=("rig", "gqrx"), ifreq=73.095)
    connect_radio(sync, "rig", 14_125_000)
    connect_radio(sync, "gqrx", -58_970_000)

    sync.nudge(100)

    assert sync.radio["rig"]["freq_queued"] == 14_125_100
    assert sync.radio["rig"]["freq_queued_is_lo"] is False
    assert_no_queue(sync, "gqrx")


def test_ifreq_rig_and_gqrx_nudge_then_sync_queues_lnb_lo_to_gqrx():
    sync = make_sync(enabled=("rig", "gqrx"), ifreq=73.095)
    connect_radio(sync, "rig", 14_125_000)
    connect_radio(sync, "gqrx", -58_970_000)

    sync.nudge(100)
    sync._apply_sync_actions()

    assert sync.radio["rig"]["freq_queued"] == 14_125_100
    assert sync.radio["gqrx"]["freq_queued"] == -58_969_900
    assert sync.radio["gqrx"]["freq_queued_is_lo"] is True


def test_ifreq_gqrx_only_nudge_queues_lnb_lo_to_gqrx():
    sync = make_sync(enabled=("gqrx",), ifreq=73.095)
    connect_radio(sync, "gqrx", -58_970_000)

    sync.nudge(100)

    assert sync.radio["gqrx"]["freq_queued"] == -58_969_900
    assert sync.radio["gqrx"]["freq_queued_is_lo"] is True
    assert_no_queue(sync, "rig")


def test_nudge_uses_freq_queued_as_base_for_accumulated_input():
    sync = make_sync(enabled=("rig",))
    connect_radio(sync, "rig", 14_125_000)

    sync.nudge(100)
    sync.nudge(100)

    assert sync.radio["rig"]["freq_queued"] == 14_125_200


def test_nudge_uses_freq_sent_as_base_when_command_is_in_flight():
    sync = make_sync(enabled=("rig",))
    connect_radio(sync, "rig", 14_125_000)

    sync.radio["rig"]["freq_sent"] = 14_125_100

    sync.nudge(100)

    assert sync.radio["rig"]["freq_queued"] == 14_125_200


def test_nudge_does_nothing_when_no_enabled_connected_radio_is_available():
    sync = make_sync(enabled=("rig", "gqrx"))

    sync.nudge(100)

    assert_no_queue(sync, "rig")
    assert_no_queue(sync, "gqrx")


def test_nudge_buffer_limit_prevents_too_large_queued_delta():
    sync = make_sync(enabled=("rig",), step_value=100)
    connect_radio(sync, "rig", 14_125_000)
    sync.cfg.sync.nudge_buffer = 1

    sync.nudge(200)

    assert_no_queue(sync, "rig")