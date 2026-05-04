from pansyncer.config import Config
from pansyncer.device_register import DeviceRegister
from pansyncer.step import StepController
from pansyncer.sync import SyncManager


class DummySocket:
    pass


def make_ifreq_gqrx_only_sync():
    cfg = Config()
    cfg.main.daemon = True
    cfg.main.ifreq = 73.095
    cfg.devices.enabled = ["gqrx"]

    devices = DeviceRegister(cfg)
    step = StepController()
    sync = SyncManager(cfg, devices, step, display=None)

    sync.radio["gqrx"].update(
        {
            "sock": DummySocket(),
            "connected": True,
            "freq_cur": -58_970_000,
            "freq_processed": -58_970_000,
            "freq_sent": None,
            "freq_queued": None,
            "freq_queued_is_lo": False,
            "query": None,
            "is_busy": None,
        }
    )

    sync.radio["rig"].update(
        {
            "sock": None,
            "connected": False,
            "freq_cur": None,
            "freq_processed": None,
            "freq_sent": None,
            "freq_queued": None,
            "freq_queued_is_lo": False,
        }
    )

    return sync


def test_ifreq_gqrx_only_get_frequency_returns_calculated_main_frequency():
    sync = make_ifreq_gqrx_only_sync()

    assert sync.get_frequency() == 14_125_000


def test_ifreq_gqrx_only_nudge_queues_lnb_lo_change():
    sync = make_ifreq_gqrx_only_sync()

    sync.nudge(100)

    assert sync.radio["gqrx"]["freq_queued"] == -58_969_900
    assert sync.radio["gqrx"]["freq_queued_is_lo"] is True
    assert sync.radio["rig"]["freq_queued"] is None


def test_ifreq_gqrx_only_set_frequency_queues_lnb_lo_from_main_frequency():
    sync = make_ifreq_gqrx_only_sync()

    assert sync.set_frequency(18_120_000) is True

    assert sync.radio["gqrx"]["freq_queued"] == -54_975_000
    assert sync.radio["gqrx"]["freq_queued_is_lo"] is True
    assert sync.radio["rig"]["freq_queued"] is None


def test_ifreq_gqrx_only_band_step_up_queues_lnb_lo_for_next_band():
    sync = make_ifreq_gqrx_only_sync()

    assert sync.band_step(1) is True

    assert sync.radio["gqrx"]["freq_queued"] == -54_975_000
    assert sync.radio["gqrx"]["freq_queued_is_lo"] is True
    assert sync.radio["rig"]["freq_queued"] is None