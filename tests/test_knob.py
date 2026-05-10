import errno
from types import SimpleNamespace

from pansyncer import knob as knob_module
from pansyncer.knob import KnobConfig, KnobController


class FakeLogger:
    def __init__(self):
        self.messages = []

    def log(self, msg, level="INFO"):
        self.messages.append((level, msg))


class FakeDisplay:
    def __init__(self):
        self.knob_states = []
        self.inputs = []
        self.step_values = []

    def set_knob(self, state):
        self.knob_states.append(state)

    def set_knob_input(self, value):
        self.inputs.append(value)

    def set_step_value(self, value):
        self.step_values.append(value)


class FakeCfg:
    def __init__(self, knobs=None):
        self.knobs = knobs or [KnobConfig()]


class FakeDevice:
    def __init__(
        self,
        path,
        *,
        name="Wired KeyBoard Consumer Control",
        vendor=0x05AC,
        product=0x0202,
        keys=None,
        grab_errno=None,
        read_error=None,
    ):
        self.path = path
        self.name = name
        self.info = SimpleNamespace(vendor=vendor, product=product)
        self._keys = keys
        self._grab_errno = grab_errno
        self._read_error = read_error
        self.fd = abs(hash(path)) % 1000 + 3
        self.grabbed = False
        self.ungrabbed = False
        self.closed = False
        self.grab_attempts = 0

    def capabilities(self):
        if self._keys is None:
            self._keys = [
                knob_module.ecodes.KEY_VOLUMEUP,
                knob_module.ecodes.KEY_VOLUMEDOWN,
                knob_module.ecodes.KEY_MUTE,
            ]
        return {knob_module.ecodes.EV_KEY: self._keys}

    def grab(self):
        self.grab_attempts += 1
        if self._grab_errno is not None:
            raise OSError(self._grab_errno, "Device or resource busy")
        self.grabbed = True

    def ungrab(self):
        self.ungrabbed = True

    def close(self):
        self.closed = True

    def read(self):
        if self._read_error:
            raise self._read_error
        return []


def patch_input_devices(monkeypatch, devices):
    by_path = {dev.path: dev for dev in devices}

    monkeypatch.setattr(knob_module, "list_devices", lambda: list(by_path))
    monkeypatch.setattr(knob_module, "InputDevice", lambda path: by_path[path])


def test_probe_device_skips_busy_matching_device_and_uses_next_match(monkeypatch):
    busy = FakeDevice("/dev/input/event10", grab_errno=errno.EBUSY)
    good = FakeDevice("/dev/input/event11")
    patch_input_devices(monkeypatch, [busy, good])

    logger = FakeLogger()

    dev = KnobController._probe_device(KnobConfig(), logger)

    assert dev is good
    assert busy.grab_attempts == 1
    assert busy.closed is True
    assert good.grab_attempts == 1
    assert good.grabbed is True
    assert good.closed is False
    assert any("device busy" in msg for _, msg in logger.messages)


def test_probe_device_closes_non_matching_and_incomplete_devices(monkeypatch):
    other = FakeDevice("/dev/input/event1", name="Other keyboard")
    incomplete = FakeDevice(
        "/dev/input/event2",
        keys=[knob_module.ecodes.KEY_VOLUMEUP],
    )
    good = FakeDevice("/dev/input/event3")
    patch_input_devices(monkeypatch, [other, incomplete, good])

    logger = FakeLogger()

    dev = KnobController._probe_device(KnobConfig(), logger)

    assert dev is good
    assert other.closed is True
    assert incomplete.closed is True
    assert good.grabbed is True
    assert good.closed is False


def test_ensure_connected_sets_display_only_after_grabbed_device_is_found(monkeypatch):
    cfg = FakeCfg()
    logger = FakeLogger()
    display = FakeDisplay()
    controller = KnobController(cfg, logger, display)

    good = FakeDevice("/dev/input/event4")
    monkeypatch.setattr(controller, "_find_input_device", lambda: good)

    assert controller.ensure_connected() is True

    assert controller.dev is good
    assert display.knob_states == [True]
    assert any("VFO-Knob connected" in msg for _, msg in logger.messages)


def test_ensure_connected_disconnects_stale_device_path_before_reconnect(monkeypatch):
    cfg = FakeCfg()
    logger = FakeLogger()
    display = FakeDisplay()
    controller = KnobController(cfg, logger, display)

    old = FakeDevice("/dev/input/event5")
    new = FakeDevice("/dev/input/event6")
    controller.dev = old
    controller.active_cfg = cfg.knobs[0]

    monkeypatch.setattr(knob_module, "list_devices", lambda: [new.path])
    monkeypatch.setattr(controller, "_find_input_device", lambda: new)

    assert controller.ensure_connected() is True

    assert old.ungrabbed is True
    assert old.closed is True
    assert controller.dev is new
    assert display.knob_states == [False, True]


def test_handle_events_disconnects_on_value_error():
    cfg = FakeCfg()
    logger = FakeLogger()
    display = FakeDisplay()
    controller = KnobController(cfg, logger, display)

    dev = FakeDevice(
        "/dev/input/event7",
        read_error=ValueError("closed evdev file descriptor"),
    )
    controller.dev = dev
    controller.active_cfg = cfg.knobs[0]

    controller.handle_events(sync=None, step=None)

    assert dev.ungrabbed is True
    assert dev.closed is True
    assert controller.dev is None
    assert controller.active_cfg is None
    assert display.knob_states == [False]
    assert any("Failed reading knob events" in msg for _, msg in logger.messages)