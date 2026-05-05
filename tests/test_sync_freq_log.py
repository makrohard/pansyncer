from pathlib import Path

from pansyncer.config import Config
from pansyncer.device_register import DeviceRegister
from pansyncer.step import StepController
from pansyncer.sync import SyncManager


def make_sync_with_freq_log(tmp_path, *, wait=0.5, ifreq=None):
    log_path = tmp_path / "freq.log"

    cfg = Config()
    cfg.main.daemon = True
    cfg.main.ifreq = ifreq
    cfg.devices.enabled = ["rig"]
    cfg.sync.freq_log_path = str(log_path)
    cfg.sync.wait_before_log_rigfreq = wait

    devices = DeviceRegister(cfg)
    step = StepController()
    sync = SyncManager(cfg, devices, step, display=None)

    sync.radio["rig"].update(
        {
            "sock": None,
            "connected": True,
            "freq_cur": None,
            "freq_processed": None,
            "freq_sent": None,
            "freq_queued": None,
            "freq_queued_is_lo": False,
            "query": None,
            "is_busy": None,
        }
    )

    sync.radio["gqrx"].update(
        {
            "sock": None,
            "connected": True,
            "freq_cur": None,
            "freq_processed": None,
            "freq_sent": None,
            "freq_queued": None,
            "freq_queued_is_lo": False,
        }
    )

    return sync, log_path


def mark_rig_frequency_change(sync, freq, changed_at):
    sync.radio["rig"]["freq_cur"] = freq
    sync._last_rig_change = changed_at
    sync._rig_reported = False


def read_log(path):
    if not Path(path).exists():
        return ""
    return Path(path).read_text(encoding="utf-8")


def count_frequency(path, freq):
    return read_log(path).count(str(freq))


def test_freq_log_waits_until_rig_freq_cur_is_stable(tmp_path):
    sync, log_path = make_sync_with_freq_log(tmp_path, wait=0.5)

    try:
        mark_rig_frequency_change(sync, 14_200_000, changed_at=10.0)

        sync._log_rig_change(0.5, 10.0)
        assert count_frequency(log_path, 14_200_000) == 0

        sync._log_rig_change(0.5, 10.4)
        assert count_frequency(log_path, 14_200_000) == 0

        sync._log_rig_change(0.5, 10.6)
        assert count_frequency(log_path, 14_200_000) == 1
    finally:
        sync.shutdown()


def test_freq_log_uses_freq_cur_not_freq_processed(tmp_path):
    sync, log_path = make_sync_with_freq_log(tmp_path, wait=0.5)

    try:
        mark_rig_frequency_change(sync, 14_200_000, changed_at=10.0)
        sync.radio["rig"]["freq_processed"] = 99_999_999

        sync._log_rig_change(0.5, 10.6)

        log_text = read_log(log_path)

        assert "14200000" in log_text
        assert "99999999" not in log_text
    finally:
        sync.shutdown()


def test_freq_log_does_not_duplicate_same_stable_freq_cur(tmp_path):
    sync, log_path = make_sync_with_freq_log(tmp_path, wait=0.5)

    try:
        mark_rig_frequency_change(sync, 14_200_000, changed_at=10.0)

        sync._log_rig_change(0.5, 10.6)
        sync._log_rig_change(0.5, 11.0)
        sync._log_rig_change(0.5, 20.0)

        assert count_frequency(log_path, 14_200_000) == 1
    finally:
        sync.shutdown()


def test_freq_log_logs_new_freq_cur_after_new_stable_change(tmp_path):
    sync, log_path = make_sync_with_freq_log(tmp_path, wait=0.5)

    try:
        mark_rig_frequency_change(sync, 14_200_000, changed_at=10.0)
        sync._log_rig_change(0.5, 10.6)

        mark_rig_frequency_change(sync, 14_250_000, changed_at=11.0)
        sync._log_rig_change(0.5, 11.0)
        assert count_frequency(log_path, 14_250_000) == 0

        sync._log_rig_change(0.5, 11.6)

        assert count_frequency(log_path, 14_200_000) == 1
        assert count_frequency(log_path, 14_250_000) == 1
    finally:
        sync.shutdown()


def test_freq_log_ignores_missing_rig_freq_cur(tmp_path):
    sync, log_path = make_sync_with_freq_log(tmp_path, wait=0.5)

    try:
        mark_rig_frequency_change(sync, None, changed_at=10.0)

        sync._log_rig_change(0.5, 20.0)

        log_text = read_log(log_path)

        assert "None" not in log_text
        assert "14200000" not in log_text
    finally:
        sync.shutdown()


def test_freq_log_in_ifreq_mode_logs_rig_freq_cur_not_gqrx_lnb_lo(tmp_path):
    sync, log_path = make_sync_with_freq_log(tmp_path, wait=0.5, ifreq=73.095)

    try:
        mark_rig_frequency_change(sync, 14_200_000, changed_at=10.0)
        sync.radio["gqrx"]["freq_cur"] = -58_895_000
        sync.radio["gqrx"]["freq_processed"] = -58_895_000

        sync._log_rig_change(0.5, 10.6)

        log_text = read_log(log_path)

        assert "14200000" in log_text
        assert "-58895000" not in log_text
        assert "58895000" not in log_text
    finally:
        sync.shutdown()