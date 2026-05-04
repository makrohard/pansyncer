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


def test_direct_sync_off_input_still_tunes_rig_but_does_not_sync_to_gqrx():
    sync = make_sync(enabled=("rig", "gqrx"))
    connect_radio(sync, "rig", 14_125_000)
    connect_radio(sync, "gqrx", 14_125_000)
    sync.set_sync_mode(False)

    sync.nudge(100)
    sync._apply_sync_actions()

    assert sync.radio["rig"]["freq_queued"] == 14_125_100
    assert sync.radio["rig"]["freq_queued_is_lo"] is False
    assert_no_queue(sync, "gqrx")


def test_direct_sync_off_external_rig_change_does_not_sync_to_gqrx():
    sync = make_sync(enabled=("rig", "gqrx"))
    connect_radio(sync, "rig", 14_200_000, freq_processed=14_125_000)
    connect_radio(sync, "gqrx", 14_125_000)
    sync.set_sync_mode(False)

    sync._apply_sync_actions()

    assert_no_queue(sync, "rig")
    assert_no_queue(sync, "gqrx")


def test_ifreq_sync_off_external_rig_change_does_not_set_gqrx_lnb_lo():
    sync = make_sync(enabled=("rig", "gqrx"), ifreq=73.095)
    connect_radio(sync, "rig", 14_200_000, freq_processed=14_125_000)
    connect_radio(sync, "gqrx", -58_970_000)
    sync.set_sync_mode(False)

    sync._apply_sync_actions()

    assert_no_queue(sync, "rig")
    assert_no_queue(sync, "gqrx")


def test_ifreq_gqrx_change_does_not_sync_back_to_rig():
    sync = make_sync(enabled=("rig", "gqrx"), ifreq=73.095)
    connect_radio(sync, "rig", 14_125_000)
    connect_radio(sync, "gqrx", -58_895_000, freq_processed=-58_970_000)

    sync._apply_sync_actions()

    assert_no_queue(sync, "rig")
    assert_no_queue(sync, "gqrx")


def test_wanted_sync_true_restores_sync_when_both_radios_are_connected_again():
    sync = make_sync(enabled=("rig", "gqrx"))
    connect_radio(sync, "rig", 14_125_000)
    connect_radio(sync, "gqrx", 14_125_000)
    sync.set_sync_mode(True)

    sync.radio["gqrx"]["connected"] = False
    sync._update_sync_state()
    assert sync.sync_on is False
    assert sync._wanted_sync is True

    sync.radio["gqrx"]["connected"] = True
    sync._update_sync_state()

    assert sync.sync_on is True


def test_wanted_sync_false_keeps_sync_off_when_both_radios_are_connected_again():
    sync = make_sync(enabled=("rig", "gqrx"))
    connect_radio(sync, "rig", 14_125_000)
    connect_radio(sync, "gqrx", 14_125_000)
    sync.set_sync_mode(False)

    sync.radio["gqrx"]["connected"] = False
    sync._update_sync_state()
    assert sync.sync_on is False
    assert sync._wanted_sync is False

    sync.radio["gqrx"]["connected"] = True
    sync._update_sync_state()

    assert sync.sync_on is False


def test_direct_simultaneous_radio_changes_prioritize_rig_without_timestamps():
    sync = make_sync(enabled=("rig", "gqrx"))
    connect_radio(sync, "rig", 14_200_000, freq_processed=14_125_000)
    connect_radio(sync, "gqrx", 14_300_000, freq_processed=14_125_000)

    sync._apply_sync_actions()

    assert sync.radio["gqrx"]["freq_queued"] == 14_200_000
    assert sync.radio["gqrx"]["freq_queued_is_lo"] is False
    assert_no_queue(sync, "rig")