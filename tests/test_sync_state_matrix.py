from pansyncer.config import Config
from pansyncer.device_register import DeviceRegister
from pansyncer.step import StepController
from pansyncer.sync import SyncManager


class DummySocket:
    pass


def make_sync(enabled=("rig", "gqrx"), ifreq=None):
    cfg = Config()
    cfg.main.daemon = True
    cfg.main.ifreq = ifreq
    cfg.devices.enabled = list(enabled)

    devices = DeviceRegister(cfg)
    step = StepController()
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


def test_direct_rig_only_set_frequency_queues_rig():
    sync = make_sync(enabled=("rig",))
    connect_radio(sync, "rig", 14_125_000)

    assert sync.set_frequency(14_200_000) is True

    assert sync.radio["rig"]["freq_queued"] == 14_200_000
    assert sync.radio["rig"]["freq_queued_is_lo"] is False
    assert_no_queue(sync, "gqrx")


def test_direct_gqrx_only_set_frequency_queues_gqrx():
    sync = make_sync(enabled=("gqrx",))
    connect_radio(sync, "gqrx", 14_125_000)

    assert sync.set_frequency(14_200_000) is True

    assert sync.radio["gqrx"]["freq_queued"] == 14_200_000
    assert sync.radio["gqrx"]["freq_queued_is_lo"] is False
    assert_no_queue(sync, "rig")


def test_direct_rig_change_queues_frequency_to_gqrx():
    sync = make_sync(enabled=("rig", "gqrx"))
    connect_radio(sync, "rig", 14_200_000, freq_processed=14_125_000)
    connect_radio(sync, "gqrx", 14_125_000, freq_processed=14_125_000)

    sync._apply_sync_actions()

    assert sync.radio["gqrx"]["freq_queued"] == 14_200_000
    assert sync.radio["gqrx"]["freq_queued_is_lo"] is False
    assert_no_queue(sync, "rig")


def test_direct_gqrx_change_queues_frequency_to_rig():
    sync = make_sync(enabled=("rig", "gqrx"))
    connect_radio(sync, "rig", 14_125_000, freq_processed=14_125_000)
    connect_radio(sync, "gqrx", 14_200_000, freq_processed=14_125_000)

    sync._apply_sync_actions()

    assert sync.radio["rig"]["freq_queued"] == 14_200_000
    assert sync.radio["rig"]["freq_queued_is_lo"] is False
    assert_no_queue(sync, "gqrx")


def test_ifreq_rig_change_queues_lnb_lo_to_gqrx():
    sync = make_sync(enabled=("rig", "gqrx"), ifreq=73.095)
    connect_radio(sync, "rig", 14_200_000, freq_processed=14_125_000)
    connect_radio(sync, "gqrx", -58_970_000, freq_processed=-58_970_000)

    sync._apply_sync_actions()

    assert sync.radio["gqrx"]["freq_queued"] == -58_895_000
    assert sync.radio["gqrx"]["freq_queued_is_lo"] is True
    assert_no_queue(sync, "rig")


def test_ifreq_rig_only_set_frequency_queues_main_frequency_to_rig():
    sync = make_sync(enabled=("rig",), ifreq=73.095)
    connect_radio(sync, "rig", 14_125_000)

    assert sync.set_frequency(18_120_000) is True

    assert sync.radio["rig"]["freq_queued"] == 18_120_000
    assert sync.radio["rig"]["freq_queued_is_lo"] is False
    assert_no_queue(sync, "gqrx")


def test_ifreq_rig_only_band_step_queues_main_frequency_to_rig():
    sync = make_sync(enabled=("rig",), ifreq=73.095)
    connect_radio(sync, "rig", 14_125_000)

    assert sync.band_step(1) is True

    assert sync.radio["rig"]["freq_queued"] == 18_120_000
    assert sync.radio["rig"]["freq_queued_is_lo"] is False
    assert_no_queue(sync, "gqrx")


def test_ifreq_rig_and_gqrx_band_step_queues_main_frequency_to_rig():
    sync = make_sync(enabled=("rig", "gqrx"), ifreq=73.095)
    connect_radio(sync, "rig", 14_125_000)
    connect_radio(sync, "gqrx", -58_970_000)

    assert sync.band_step(1) is True

    assert sync.radio["rig"]["freq_queued"] == 18_120_000
    assert sync.radio["rig"]["freq_queued_is_lo"] is False
    assert_no_queue(sync, "gqrx")