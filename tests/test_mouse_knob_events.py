from types import SimpleNamespace

import evdev

from pansyncer.knob import KnobConfig, KnobController
from pansyncer.mouse import MouseState


class FakeEvent:
    def __init__(self, event_type, code, value):
        self.type = event_type
        self.code = code
        self.value = value


class FakeInputDevice:
    def __init__(
        self,
        fd,
        events,
        path=None,
        name="Fake Input Device",
        caps=None,
    ):
        self.fd = fd
        self.path = path if path is not None else f"/dev/input/event{fd}"
        self.name = name
        self._events = list(events)
        self.closed = False
        self.close_calls = 0
        self.grab_calls = 0
        self.ungrab_calls = 0
        self._caps = caps if caps is not None else {
            evdev.ecodes.EV_REL: [evdev.ecodes.REL_WHEEL],
            evdev.ecodes.EV_KEY: [evdev.ecodes.BTN_MIDDLE],
        }

    def capabilities(self):
        return self._caps

    def read(self):
        events = self._events
        self._events = []
        return events

    def grab(self):
        self.grab_calls += 1

    def ungrab(self):
        self.ungrab_calls += 1

    def close(self):
        self.close_calls += 1
        self.closed = True

class FakeSync:
    def __init__(self):
        self.nudges = []

    def nudge(self, delta_hz):
        self.nudges.append(delta_hz)


class FakeStep:
    def __init__(self, value=100):
        self.value = value
        self.next_calls = 0

    def get_step(self):
        return self.value

    def next_step(self):
        self.next_calls += 1


class FakeDisplay:
    def __init__(self):
        self.mouse_inputs = []
        self.knob_inputs = []
        self.step_values = []
        self.mouse_states = []
        self.knob_states = []

    def set_mouse_input(self, text):
        self.mouse_inputs.append(text)

    def set_knob_input(self, text):
        self.knob_inputs.append(text)

    def set_step_value(self, step):
        self.step_values.append(step)

    def set_mouse(self, connected):
        self.mouse_states.append(connected)

    def set_knob(self, connected):
        self.knob_states.append(connected)


class FakeLogger:
    def __init__(self):
        self.messages = []

    def log(self, msg, level="INFO"):
        self.messages.append((level, msg))

class FakeInputDeviceFactory:
    def __init__(self, devices_by_path):
        self.devices_by_path = devices_by_path
        self.opened = []

    def __call__(self, path):
        self.opened.append(path)
        return self.devices_by_path[path]


def install_mouse_discovery(monkeypatch, paths, devices_by_path):
    factory = FakeInputDeviceFactory(devices_by_path)

    monkeypatch.setattr(evdev, "list_devices", lambda: list(paths))
    monkeypatch.setattr(evdev, "InputDevice", factory)

    return factory

def make_mouse_state(fake_device, display=None):
    mouse = MouseState.__new__(MouseState)
    mouse.display = display if display is not None else FakeDisplay()
    mouse.logger = FakeLogger()
    mouse.mice = [fake_device]
    mouse.last_scroll_time = 0.0
    return mouse


def make_knob_controller(fake_device, display=None):
    knob = KnobController.__new__(KnobController)
    knob.cfg = SimpleNamespace(knobs=[])
    knob.display = display if display is not None else FakeDisplay()
    knob.logger = FakeLogger()
    knob.dev = fake_device
    knob.active_cfg = KnobConfig(
        key_up=evdev.ecodes.KEY_VOLUMEUP,
        key_down=evdev.ecodes.KEY_VOLUMEDOWN,
        key_step=evdev.ecodes.KEY_MUTE,
    )
    return knob


def test_mouse_wheel_up_nudges_positive_step_and_sets_indicator():
    event = FakeEvent(evdev.ecodes.EV_REL, evdev.ecodes.REL_WHEEL, 1)
    fake_device = FakeInputDevice(fd=10, events=[event])
    display = FakeDisplay()
    mouse = make_mouse_state(fake_device, display=display)
    sync = FakeSync()
    step = FakeStep(100)

    mouse.handle_event(10, sync, step, now=12.0)

    assert sync.nudges == [100]
    assert display.mouse_inputs == ["UP "]
    assert mouse.last_scroll_time == 12.0


def test_mouse_wheel_down_nudges_negative_step_and_sets_indicator():
    event = FakeEvent(evdev.ecodes.EV_REL, evdev.ecodes.REL_WHEEL, -1)
    fake_device = FakeInputDevice(fd=10, events=[event])
    display = FakeDisplay()
    mouse = make_mouse_state(fake_device, display=display)
    sync = FakeSync()
    step = FakeStep(100)

    mouse.handle_event(10, sync, step, now=12.0)

    assert sync.nudges == [-100]
    assert display.mouse_inputs == ["DWN"]
    assert mouse.last_scroll_time == 12.0


def test_mouse_middle_click_cycles_step_and_sets_indicator():
    event = FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.BTN_MIDDLE, 1)
    fake_device = FakeInputDevice(fd=10, events=[event])
    display = FakeDisplay()
    mouse = make_mouse_state(fake_device, display=display)
    sync = FakeSync()
    step = FakeStep(100)

    mouse.handle_event(10, sync, step, now=12.0)

    assert sync.nudges == []
    assert step.next_calls == 1
    assert display.step_values == [100]
    assert display.mouse_inputs == ["STP"]


def test_mouse_middle_release_is_ignored():
    event = FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.BTN_MIDDLE, 0)
    fake_device = FakeInputDevice(fd=10, events=[event])
    display = FakeDisplay()
    mouse = make_mouse_state(fake_device, display=display)
    sync = FakeSync()
    step = FakeStep(100)

    mouse.handle_event(10, sync, step, now=12.0)

    assert sync.nudges == []
    assert step.next_calls == 0
    assert display.mouse_inputs == []


def test_mouse_unknown_fd_is_ignored():
    event = FakeEvent(evdev.ecodes.EV_REL, evdev.ecodes.REL_WHEEL, 1)
    fake_device = FakeInputDevice(fd=10, events=[event])
    display = FakeDisplay()
    mouse = make_mouse_state(fake_device, display=display)
    sync = FakeSync()
    step = FakeStep(100)

    mouse.handle_event(99, sync, step, now=12.0)

    assert sync.nudges == []
    assert display.mouse_inputs == []


def test_knob_volume_up_nudges_positive_step_and_sets_indicator():
    event = FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_VOLUMEUP, 1)
    fake_device = FakeInputDevice(fd=20, events=[event])
    display = FakeDisplay()
    knob = make_knob_controller(fake_device, display=display)
    sync = FakeSync()
    step = FakeStep(100)

    knob.handle_events(sync, step)

    assert sync.nudges == [100]
    assert display.step_values == [100]
    assert display.knob_inputs == ["UP "]


def test_knob_volume_down_nudges_negative_step_and_sets_indicator():
    event = FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_VOLUMEDOWN, 1)
    fake_device = FakeInputDevice(fd=20, events=[event])
    display = FakeDisplay()
    knob = make_knob_controller(fake_device, display=display)
    sync = FakeSync()
    step = FakeStep(100)

    knob.handle_events(sync, step)

    assert sync.nudges == [-100]
    assert display.step_values == [100]
    assert display.knob_inputs == ["DWN"]


def test_knob_mute_cycles_step_and_sets_indicator():
    event = FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_MUTE, 1)
    fake_device = FakeInputDevice(fd=20, events=[event])
    display = FakeDisplay()
    knob = make_knob_controller(fake_device, display=display)
    sync = FakeSync()
    step = FakeStep(100)

    knob.handle_events(sync, step)

    assert sync.nudges == []
    assert step.next_calls == 1
    assert display.step_values == [100]
    assert display.knob_inputs == ["STP"]


def test_knob_key_release_is_ignored():
    event = FakeEvent(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_VOLUMEUP, 0)
    fake_device = FakeInputDevice(fd=20, events=[event])
    display = FakeDisplay()
    knob = make_knob_controller(fake_device, display=display)
    sync = FakeSync()
    step = FakeStep(100)

    knob.handle_events(sync, step)

    assert sync.nudges == []
    assert step.next_calls == 0
    assert display.knob_inputs == []


def test_knob_non_key_event_is_ignored():
    event = FakeEvent(evdev.ecodes.EV_REL, evdev.ecodes.REL_WHEEL, 1)
    fake_device = FakeInputDevice(fd=20, events=[event])
    display = FakeDisplay()
    knob = make_knob_controller(fake_device, display=display)
    sync = FakeSync()
    step = FakeStep(100)

    knob.handle_events(sync, step)

    assert sync.nudges == []
    assert step.next_calls == 0
    assert display.knob_inputs == []

class FailingReadMouseDevice(FakeInputDevice):
    def read(self):
        raise OSError("mouse gone")


class FailingUngrabKnobDevice(FakeInputDevice):
    def __init__(self, fd, events):
        super().__init__(fd, events)
        self.ungrab_calls = 0
        self.close_calls = 0

    def ungrab(self):
        self.ungrab_calls += 1
        raise OSError("ungrab failed")

    def close(self):
        self.close_calls += 1
        self.closed = True


def test_mouse_read_error_keeps_display_connected_when_other_mouse_remains():
    failing = FailingReadMouseDevice(fd=10, events=[])
    remaining = FakeInputDevice(fd=11, events=[])
    display = FakeDisplay()
    mouse = make_mouse_state(failing, display=display)
    mouse.mice.append(remaining)

    sync = FakeSync()
    step = FakeStep(100)

    mouse.handle_event(10, sync, step, now=12.0)

    assert failing.closed is True
    assert remaining in mouse.mice
    assert failing not in mouse.mice
    assert display.mouse_states[-1] is True


def test_mouse_wheel_zero_value_is_ignored():
    event = FakeEvent(evdev.ecodes.EV_REL, evdev.ecodes.REL_WHEEL, 0)
    fake_device = FakeInputDevice(fd=10, events=[event])
    display = FakeDisplay()
    mouse = make_mouse_state(fake_device, display=display)
    sync = FakeSync()
    step = FakeStep(100)

    mouse.handle_event(10, sync, step, now=12.0)

    assert sync.nudges == []
    assert display.mouse_inputs == []


def test_knob_disconnect_closes_device_even_when_ungrab_fails():
    fake_device = FailingUngrabKnobDevice(fd=20, events=[])
    display = FakeDisplay()
    knob = make_knob_controller(fake_device, display=display)

    knob.disconnect()

    assert fake_device.ungrab_calls == 1
    assert fake_device.close_calls == 1
    assert fake_device.closed is True
    assert knob.dev is None
    assert knob.active_cfg is None
    assert display.knob_states[-1] is False

def test_mouse_rescan_adds_new_mouse_even_when_existing_mouse_present(monkeypatch):
    dead_mouse = FakeInputDevice(
        fd=10,
        events=[],
        path="/dev/input/event10",
        name="Dead knob mouse",
    )
    real_mouse = FakeInputDevice(
        fd=11,
        events=[],
        path="/dev/input/event11",
        name="Real mouse",
    )

    paths = [dead_mouse.path]
    devices_by_path = {
        dead_mouse.path: dead_mouse,
        real_mouse.path: real_mouse,
    }
    display = FakeDisplay()
    install_mouse_discovery(monkeypatch, paths, devices_by_path)

    mouse = MouseState(now=0.0, logger=FakeLogger(), display=display)

    assert mouse.mice == [dead_mouse]

    paths.append(real_mouse.path)

    assert mouse.ensure_connected() is True

    assert mouse.mice == [dead_mouse, real_mouse]
    assert display.mouse_states[-1] is True


def test_mouse_rescan_does_not_open_existing_mouse_twice(monkeypatch):
    mouse_device = FakeInputDevice(
        fd=10,
        events=[],
        path="/dev/input/event10",
        name="Mouse",
    )

    paths = [mouse_device.path]
    devices_by_path = {mouse_device.path: mouse_device}
    factory = install_mouse_discovery(monkeypatch, paths, devices_by_path)

    mouse = MouseState(now=0.0, logger=FakeLogger(), display=FakeDisplay())

    assert mouse.mice == [mouse_device]
    assert factory.opened == [mouse_device.path]

    assert mouse.ensure_connected() is True

    assert mouse.mice == [mouse_device]
    assert factory.opened == [mouse_device.path]


def test_mouse_rescan_removes_disappeared_mouse(monkeypatch):
    removed_mouse = FakeInputDevice(
        fd=10,
        events=[],
        path="/dev/input/event10",
        name="Removed mouse",
    )
    remaining_mouse = FakeInputDevice(
        fd=11,
        events=[],
        path="/dev/input/event11",
        name="Remaining mouse",
    )

    paths = [removed_mouse.path, remaining_mouse.path]
    devices_by_path = {
        removed_mouse.path: removed_mouse,
        remaining_mouse.path: remaining_mouse,
    }
    display = FakeDisplay()
    install_mouse_discovery(monkeypatch, paths, devices_by_path)

    mouse = MouseState(now=0.0, logger=FakeLogger(), display=display)

    assert mouse.mice == [removed_mouse, remaining_mouse]

    paths.remove(removed_mouse.path)

    assert mouse.ensure_connected() is True

    assert removed_mouse.closed is True
    assert remaining_mouse.closed is False
    assert mouse.mice == [remaining_mouse]
    assert display.mouse_states[-1] is True


def test_dead_knob_mouse_does_not_block_later_real_mouse_events(monkeypatch):
    dead_mouse = FakeInputDevice(
        fd=10,
        events=[],
        path="/dev/input/event10",
        name="Dead knob mouse",
    )
    real_mouse = FakeInputDevice(
        fd=11,
        events=[
            FakeEvent(evdev.ecodes.EV_REL, evdev.ecodes.REL_WHEEL, 1),
        ],
        path="/dev/input/event11",
        name="Real mouse",
    )

    paths = [dead_mouse.path]
    devices_by_path = {
        dead_mouse.path: dead_mouse,
        real_mouse.path: real_mouse,
    }
    display = FakeDisplay()
    install_mouse_discovery(monkeypatch, paths, devices_by_path)

    mouse = MouseState(now=0.0, logger=FakeLogger(), display=display)

    paths.append(real_mouse.path)

    assert mouse.ensure_connected() is True

    sync = FakeSync()
    step = FakeStep(100)

    mouse.handle_event(real_mouse.fd, sync, step, now=12.0)

    assert sync.nudges == [100]
    assert display.mouse_inputs == ["UP "]