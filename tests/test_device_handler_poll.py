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


def test_poll_inputs_removes_knob_and_mouse_on_select_ebadf(monkeypatch):
    handler = make_handler_without_devices()
    handler.devices._devices.update({"knob", "mouse"})

    class FakeKnob:
        def fd(self):
            return 10

    class FakeMouse:
        def get_fds(self):
            return [11]

    handler._knob = FakeKnob()
    handler._mouse = FakeMouse()

    removed = []

    def fake_remove(dev):
        removed.append(dev)
        handler.devices._devices.discard(dev)
        return True

    def fake_select(*args, **kwargs):
        raise OSError(errno.EBADF, "Bad file descriptor")

    monkeypatch.setattr(handler.devices, "remove", fake_remove)
    monkeypatch.setattr(select, "select", fake_select)

    assert handler._poll_inputs(now=10.0) is False

    assert removed == ["knob", "mouse"]