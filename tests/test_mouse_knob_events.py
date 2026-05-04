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
    def __init__(self, fd, events):
        self.fd = fd
        self._events = list(events)
        self.closed = False

    def read(self):
        events = self._events
        self._events = []
        return events

    def close(self):
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