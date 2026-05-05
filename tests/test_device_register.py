from pansyncer.config import Config
from pansyncer.device_register import DeviceRegister


class FakeLogger:
    def __init__(self):
        self.messages = []

    def log(self, msg, level="INFO"):
        self.messages.append((level, msg))


def make_cfg(*, enabled=None, daemon=False):
    cfg = Config()
    cfg.main.daemon = daemon
    cfg.devices.enabled = list(enabled or [])
    return cfg


def test_non_daemon_adds_keyboard_even_if_not_configured():
    cfg = make_cfg(enabled=["rig"], daemon=False)

    devices = DeviceRegister(cfg)

    assert devices.list() == {"rig", "keyboard"}


def test_daemon_removes_interactive_input_devices():
    cfg = make_cfg(
        enabled=["rig", "gqrx", "keyboard", "knob", "mouse"],
        daemon=True,
    )

    devices = DeviceRegister(cfg)

    assert devices.list() == {"rig", "gqrx"}


def test_initial_devices_bypass_config_and_daemon_filter():
    cfg = make_cfg(enabled=["rig", "gqrx"], daemon=True)

    devices = DeviceRegister(cfg, initial=["mouse"])

    assert devices.list() == {"mouse"}


def test_enabled_reports_current_device_state():
    cfg = make_cfg(enabled=["rig"], daemon=True)
    devices = DeviceRegister(cfg)

    assert devices.enabled("rig") is True
    assert devices.enabled("gqrx") is False


def test_list_returns_snapshot_not_internal_set():
    cfg = make_cfg(enabled=["rig"], daemon=True)
    devices = DeviceRegister(cfg)

    snapshot = devices.list()
    snapshot.add("fake")

    assert devices.enabled("fake") is False
    assert devices.list() == {"rig"}


def test_add_device_calls_on_add_once():
    cfg = make_cfg(enabled=["rig"], daemon=True)
    devices = DeviceRegister(cfg)
    added = []

    devices.on_add(added.append)

    devices.add("knob")
    devices.add("knob")

    assert added == ["knob"]
    assert devices.enabled("knob") is True


def test_remove_device_calls_on_remove_once():
    cfg = make_cfg(enabled=["rig"], daemon=True)
    devices = DeviceRegister(cfg, initial=["rig", "knob"])
    removed = []

    devices.on_remove(removed.append)

    devices.remove("knob")
    devices.remove("knob")

    assert removed == ["knob"]
    assert devices.enabled("knob") is False


def test_toggle_non_radio_device_removes_and_adds_again():
    cfg = make_cfg(enabled=["rig"], daemon=True)
    devices = DeviceRegister(cfg, initial=["rig", "knob"])

    assert devices.toggle("knob") is True
    assert devices.enabled("knob") is False

    assert devices.toggle("knob") is True
    assert devices.enabled("knob") is True


def test_toggle_refuses_to_disable_last_radio(monkeypatch):
    cfg = make_cfg(enabled=["rig"], daemon=True)
    logger = FakeLogger()
    devices = DeviceRegister(cfg, logger=logger)
    beep_calls = []

    monkeypatch.setattr("pansyncer.device_register.beep", lambda: beep_calls.append("beep"))

    assert devices.toggle("rig") is False

    assert devices.enabled("rig") is True
    assert beep_calls == ["beep"]
    assert any("Cannot disable last radio device" in msg for _, msg in logger.messages)


def test_toggle_radio_allowed_when_other_radio_is_enabled():
    cfg = make_cfg(enabled=["rig", "gqrx"], daemon=True)
    devices = DeviceRegister(cfg)

    assert devices.toggle("rig") is True
    assert devices.enabled("rig") is False
    assert devices.enabled("gqrx") is True

    assert devices.toggle("rig") is True
    assert devices.enabled("rig") is True
    assert devices.enabled("gqrx") is True

def test_unknown_initial_devices_are_ignored():
    cfg = Config()
    cfg.main.daemon = False
    cfg.devices.enabled = ["rig", "keyboard", "bogus"]

    devices = DeviceRegister(cfg)

    assert devices.enabled("rig") is True
    assert devices.enabled("keyboard") is True
    assert devices.enabled("bogus") is False


def test_toggle_unknown_device_is_rejected(monkeypatch):
    cfg = Config()
    devices = DeviceRegister(cfg)
    beeps = []

    monkeypatch.setattr("pansyncer.device_register.beep", lambda: beeps.append(True))

    assert devices.toggle("bogus") is False
    assert devices.enabled("bogus") is False
    assert beeps == [True]


def test_add_unknown_device_is_rejected(monkeypatch):
    cfg = Config()
    devices = DeviceRegister(cfg)
    added = []
    beeps = []

    devices.on_add(added.append)
    monkeypatch.setattr("pansyncer.device_register.beep", lambda: beeps.append(True))

    assert devices.add("bogus") is False
    assert devices.enabled("bogus") is False
    assert added == []
    assert beeps == [True]


def test_cannot_disable_last_radio_device(monkeypatch):
    cfg = Config()
    devices = DeviceRegister(cfg, initial=["rig"])
    beeps = []

    monkeypatch.setattr("pansyncer.device_register.beep", lambda: beeps.append(True))

    assert devices.toggle("rig") is False
    assert devices.enabled("rig") is True
    assert beeps == [True]