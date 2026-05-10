import errno
import select

from pansyncer.config import Config
from pansyncer.device_handler import DeviceHandler
from pansyncer.device_register import DeviceRegister


class FakeLogger:
    def __init__(self):
        self.messages = []

    def log(self, msg, level="INFO"):
        self.messages.append((level, msg))


def make_handler_without_devices():
    cfg = Config()
    cfg.main.daemon = True
    cfg.devices.enabled = []

    devices = DeviceRegister(cfg)
    logger = FakeLogger()

    handler = DeviceHandler(
        cfg=cfg,
        is_tty=False,
        devices=devices,
        logger=logger,
        sync=None,
        step=None,
        display=None,
        keyboard=None,
    )

    return handler


def test_poll_inputs_refreshes_only_bad_mouse_fd_on_select_ebadf(monkeypatch):
    handler = make_handler_without_devices()
    handler.devices._devices.update({"knob", "mouse"})

    knob_disconnects = []
    mouse_refreshes = []

    class FakeKnob:
        def fd(self):
            return 10

        def disconnect(self):
            knob_disconnects.append("knob")

    class FakeMouse:
        def get_fds(self):
            return [11]

        def refresh(self):
            mouse_refreshes.append("mouse")
            return False

    handler._knob = FakeKnob()
    handler._mouse = FakeMouse()

    def fake_remove(dev):
        raise AssertionError(f"device must not be removed on hardware EBADF: {dev}")

    def fake_select(*args, **kwargs):
        raise OSError(errno.EBADF, "Bad file descriptor")

    monkeypatch.setattr(handler.devices, "remove", fake_remove)
    monkeypatch.setattr(select, "select", fake_select)
    monkeypatch.setattr(handler, "_fd_is_valid", lambda fd: fd != 11)

    assert handler._poll_inputs(now=10.0) is False

    assert knob_disconnects == []
    assert mouse_refreshes == ["mouse"]
    assert handler.devices.enabled("knob") is True
    assert handler.devices.enabled("mouse") is True


def test_poll_inputs_disconnects_only_bad_knob_fd_on_select_ebadf(monkeypatch):
    handler = make_handler_without_devices()
    handler.devices._devices.update({"knob", "mouse"})

    knob_disconnects = []
    mouse_refreshes = []

    class FakeKnob:
        def fd(self):
            return 10

        def disconnect(self):
            knob_disconnects.append("knob")

    class FakeMouse:
        def get_fds(self):
            return [11]

        def refresh(self):
            mouse_refreshes.append("mouse")
            return False

    handler._knob = FakeKnob()
    handler._mouse = FakeMouse()

    def fake_remove(dev):
        raise AssertionError(f"device must not be removed on hardware EBADF: {dev}")

    def fake_select(*args, **kwargs):
        raise OSError(errno.EBADF, "Bad file descriptor")

    monkeypatch.setattr(handler.devices, "remove", fake_remove)
    monkeypatch.setattr(select, "select", fake_select)
    monkeypatch.setattr(handler, "_fd_is_valid", lambda fd: fd != 10)

    assert handler._poll_inputs(now=10.0) is False

    assert knob_disconnects == ["knob"]
    assert mouse_refreshes == []
    assert handler.devices.enabled("knob") is True
    assert handler.devices.enabled("mouse") is True


def test_poll_inputs_refreshes_knob_on_fd_error_without_removing_device(monkeypatch):
    handler = make_handler_without_devices()
    handler.devices._devices.update({"knob"})

    refreshes = []

    class FakeKnob:
        def fd(self):
            raise OSError("bad knob fd")

        def disconnect(self):
            refreshes.append("knob")

    handler._knob = FakeKnob()

    def fake_remove(dev):
        raise AssertionError(f"device must not be removed on knob fd error: {dev}")

    monkeypatch.setattr(handler.devices, "remove", fake_remove)

    assert handler._poll_inputs(now=10.0) is False

    assert refreshes == ["knob"]
    assert handler.devices.enabled("knob") is True


def test_poll_inputs_refreshes_knob_on_fd_value_error_without_removing_device(monkeypatch):
    handler = make_handler_without_devices()
    handler.devices._devices.update({"knob"})

    refreshes = []

    class FakeKnob:
        def fd(self):
            raise ValueError("closed knob fd")

        def disconnect(self):
            refreshes.append("knob")

    handler._knob = FakeKnob()

    def fake_remove(dev):
        raise AssertionError(f"device must not be removed on knob fd ValueError: {dev}")

    monkeypatch.setattr(handler.devices, "remove", fake_remove)

    assert handler._poll_inputs(now=10.0) is False

    assert refreshes == ["knob"]
    assert handler.devices.enabled("knob") is True


def test_poll_inputs_refreshes_mouse_on_fd_value_error_without_removing_device(monkeypatch):
    handler = make_handler_without_devices()
    handler.devices._devices.update({"mouse"})

    refreshes = []

    class FakeMouse:
        def get_fds(self):
            raise ValueError("closed mouse fd")

        def refresh(self):
            refreshes.append("mouse")
            return False

    handler._mouse = FakeMouse()

    def fake_remove(dev):
        raise AssertionError(f"device must not be removed on mouse fd ValueError: {dev}")

    monkeypatch.setattr(handler.devices, "remove", fake_remove)

    assert handler._poll_inputs(now=10.0) is False

    assert refreshes == ["mouse"]
    assert handler.devices.enabled("mouse") is True


def test_poll_inputs_refreshes_knob_after_handler_error(monkeypatch):
    handler = make_handler_without_devices()
    handler.devices._devices.update({"knob"})

    refreshes = []

    class FakeKnob:
        def fd(self):
            return 10

        def handle_events(self, sync, step):
            raise ValueError("knob disappeared while reading")

        def disconnect(self):
            refreshes.append("knob")

    handler._knob = FakeKnob()

    monkeypatch.setattr(select, "select", lambda *args, **kwargs: ([10], [], []))

    assert handler._poll_inputs(now=10.0) is False

    assert refreshes == ["knob"]
    assert handler.devices.enabled("knob") is True


def test_poll_inputs_refreshes_mouse_after_handler_error(monkeypatch):
    handler = make_handler_without_devices()
    handler.devices._devices.update({"mouse"})

    refreshes = []

    class FakeMouse:
        def get_fds(self):
            return [11]

        def handle_event(self, fd, sync, step, now):
            raise ValueError("mouse disappeared while reading")

        def refresh(self):
            refreshes.append("mouse")
            return False

    handler._mouse = FakeMouse()

    monkeypatch.setattr(select, "select", lambda *args, **kwargs: ([11], [], []))

    assert handler._poll_inputs(now=10.0) is False

    assert refreshes == ["mouse"]
    assert handler.devices.enabled("mouse") is True


def test_poll_inputs_does_not_refresh_replaced_knob_controller(monkeypatch):
    handler = make_handler_without_devices()
    handler.devices._devices.update({"knob"})

    old_refreshes = []
    new_refreshes = []

    class OldKnob:
        def fd(self):
            return 10

        def handle_events(self, sync, step):
            handler._knob = NewKnob()
            raise ValueError("old knob disappeared")

        def disconnect(self):
            old_refreshes.append("old")

    class NewKnob:
        def disconnect(self):
            new_refreshes.append("new")

    handler._knob = OldKnob()

    monkeypatch.setattr(select, "select", lambda *args, **kwargs: ([10], [], []))

    assert handler._poll_inputs(now=10.0) is False

    assert old_refreshes == []
    assert new_refreshes == []
    assert isinstance(handler._knob, NewKnob)
    assert handler.devices.enabled("knob") is True