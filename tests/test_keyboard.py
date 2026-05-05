from types import SimpleNamespace
import os

import pytest

from pansyncer.keyboard import KeyboardController


class FakeDevices:
    def __init__(self, enabled=None):
        self._enabled = set(enabled or ["rig", "gqrx", "keyboard", "knob", "mouse"])
        self.toggled = []

    def enabled(self, dev):
        return dev in self._enabled

    def toggle(self, dev):
        self.toggled.append(dev)
        if dev in self._enabled:
            self._enabled.remove(dev)
        else:
            self._enabled.add(dev)
        return True


class FakeSync:
    def __init__(self, rig_ok=True, gqrx_ok=True):
        self.nudges = []
        self.sync_modes = []
        self.band_steps = []
        self.radio = {
            "rig": {
                "sock": object() if rig_ok else None,
                "connected": rig_ok,
            },
            "gqrx": {
                "sock": object() if gqrx_ok else None,
                "connected": gqrx_ok,
            },
        }

    def nudge(self, delta_hz):
        self.nudges.append(delta_hz)

    def set_sync_mode(self, state):
        self.sync_modes.append(state)

    def band_step(self, direction):
        self.band_steps.append(direction)
        return True


class FakeStep:
    def __init__(self, value=100):
        self.value = value
        self.next_calls = 0

    def get_step(self):
        return self.value

    def next_step(self):
        self.next_calls += 1


class FakeLogger:
    def __init__(self):
        self.messages = []

    def log(self, msg, level="INFO"):
        self.messages.append((level, msg))


class FakeDisplay:
    def __init__(self):
        self.keyboard_inputs = []
        self.sync_modes = []
        self.step_values = []
        self.cfg = SimpleNamespace(display=SimpleNamespace(small_display=False))

    def set_keyboard_input(self, text):
        self.keyboard_inputs.append(text)

    def set_sync_mode(self, state):
        self.sync_modes.append(state)

    def set_step_value(self, step):
        self.step_values.append(step)

    def toggle_small_display(self):
        self.cfg.display.small_display = not self.cfg.display.small_display


def make_keyboard(*, sync=None, devices=None, step=None, display=None, mouse=None):
    keyboard = KeyboardController.__new__(KeyboardController)
    keyboard.interval = 0.1
    keyboard.devices = devices or FakeDevices()
    keyboard.sync = sync or FakeSync()
    keyboard.logger = FakeLogger()
    keyboard.step = step or FakeStep()
    keyboard.display = display if display is not None else FakeDisplay()
    keyboard.mouse = mouse
    keyboard._fd = 123
    keyboard.focused = True
    keyboard._paste_mode = False
    keyboard._input_buf = bytearray()
    return keyboard


def test_plus_and_minus_nudge_by_current_step():
    sync = FakeSync()
    display = FakeDisplay()
    keyboard = make_keyboard(sync=sync, display=display)

    keyboard.handle_events("+")
    keyboard.handle_events("-")

    assert sync.nudges == [100, -100]
    assert display.keyboard_inputs == ["UP ", "DWN"]


def test_space_cycles_step_and_updates_display():
    step = FakeStep(value=100)
    display = FakeDisplay()
    keyboard = make_keyboard(step=step, display=display)

    keyboard.handle_events(" ")

    assert step.next_calls == 1
    assert display.step_values == [100]
    assert display.keyboard_inputs == ["STP"]


@pytest.mark.parametrize(
    ("key", "device", "indicator"),
    [
        ("r", "rig", "RIG"),
        ("g", "gqrx", "GQR"),
        ("k", "knob", "KNB"),
        ("m", "mouse", "MSE"),
    ],
)
def test_device_toggle_keys_toggle_expected_device(key, device, indicator):
    devices = FakeDevices()
    display = FakeDisplay()
    keyboard = make_keyboard(devices=devices, display=display)

    keyboard.handle_events(key)

    assert devices.toggled == [device]
    assert display.keyboard_inputs == [indicator]


def test_sync_on_requires_rig_and_gqrx_connected():
    sync = FakeSync(rig_ok=True, gqrx_ok=True)
    display = FakeDisplay()
    keyboard = make_keyboard(sync=sync, display=display)

    keyboard.handle_events("1")

    assert sync.sync_modes == [True]
    assert display.sync_modes == [True]


def test_sync_on_fails_when_one_radio_is_missing():
    sync = FakeSync(rig_ok=True, gqrx_ok=False)
    display = FakeDisplay()
    keyboard = make_keyboard(sync=sync, display=display)

    keyboard.handle_events("1")

    assert sync.sync_modes == [False]
    assert display.sync_modes == [False]


def test_sync_off_disables_sync():
    sync = FakeSync()
    display = FakeDisplay()
    keyboard = make_keyboard(sync=sync, display=display)

    keyboard.handle_events("0")

    assert sync.sync_modes == [False]
    assert display.sync_modes == [False]


def test_band_up_and_down_keys_call_band_step():
    sync = FakeSync()
    display = FakeDisplay()
    keyboard = make_keyboard(sync=sync, display=display)

    keyboard.handle_events("w")
    keyboard.handle_events("s")

    assert sync.band_steps == [1, -1]
    assert display.keyboard_inputs == ["BUP", "BDN"]


def test_display_toggle_key_toggles_small_display():
    display = FakeDisplay()
    keyboard = make_keyboard(display=display)

    keyboard.handle_events("d")

    assert display.cfg.display.small_display is True
    assert display.keyboard_inputs == ["DSP"]


def test_quit_key_returns_quit_and_sets_indicator():
    display = FakeDisplay()
    keyboard = make_keyboard(display=display)

    result = keyboard.handle_events("q")

    assert result == "quit"
    assert display.keyboard_inputs == ["EXT"]


def test_read_stdin_arrow_keys_trigger_nudge(monkeypatch):
    sync = FakeSync()
    mouse = SimpleNamespace(last_scroll_time=-999.0)
    keyboard = make_keyboard(sync=sync, mouse=mouse)

    monkeypatch.setattr(os, "read", lambda fd, size: b"\x1b[A\x1b[B")

    assert keyboard.read_stdin(123, now=10.0) is False
    assert sync.nudges == [100, -100]


def test_read_stdin_arrow_keys_are_ignored_after_recent_mouse_scroll(monkeypatch):
    sync = FakeSync()
    mouse = SimpleNamespace(last_scroll_time=9.95)
    keyboard = make_keyboard(sync=sync, mouse=mouse)

    monkeypatch.setattr(os, "read", lambda fd, size: b"\x1b[A\x1b[B")

    assert keyboard.read_stdin(123, now=10.0) is False
    assert sync.nudges == []


def test_read_stdin_focus_sequences_update_focus_state(monkeypatch):
    keyboard = make_keyboard()

    reads = iter([b"\x1b[O", b"\x1b[I"])
    monkeypatch.setattr(os, "read", lambda fd, size: next(reads))

    assert keyboard.read_stdin(123, now=10.0) is False
    assert keyboard.focused is False

    assert keyboard.read_stdin(123, now=10.1) is False
    assert keyboard.focused is True


def test_read_stdin_ignores_bracketed_paste(monkeypatch):
    sync = FakeSync()
    keyboard = make_keyboard(sync=sync)

    monkeypatch.setattr(os, "read", lambda fd, size: b"\x1b[200~+q-\x1b[201~")

    assert keyboard.read_stdin(123, now=10.0) is False
    assert sync.nudges == []


def test_read_stdin_buffers_incomplete_escape_sequence(monkeypatch):
    sync = FakeSync()
    keyboard = make_keyboard(sync=sync)

    reads = iter([b"\x1b[", b"A"])
    monkeypatch.setattr(os, "read", lambda fd, size: next(reads))

    assert keyboard.read_stdin(123, now=10.0) is False
    assert keyboard._input_buf == bytearray(b"\x1b[")
    assert sync.nudges == []

    assert keyboard.read_stdin(123, now=10.1) is False
    assert keyboard._input_buf == bytearray()
    assert sync.nudges == [100]

def test_read_stdin_returns_quit_on_eof(monkeypatch):
    keyboard = make_keyboard()

    monkeypatch.setattr(os, "read", lambda fd, size: b"")

    assert keyboard.read_stdin(123, now=10.0) is True
    assert keyboard._input_buf == bytearray()