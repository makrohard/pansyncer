from types import SimpleNamespace

from pansyncer.config import Config
from pansyncer.device_register import DeviceRegister
from pansyncer.display import Display


def make_display(*, enabled=("rig", "gqrx", "keyboard", "knob", "mouse"), small=False):
    cfg = Config()
    cfg.main.daemon = False
    cfg.devices.enabled = list(enabled)
    cfg.display.small_display = small

    devices = DeviceRegister(cfg)
    return Display(cfg, devices, is_tty=False)


def clear_redraw(display):
    display._redraw = False


def test_set_sync_mode_updates_value_and_marks_redraw():
    display = make_display()
    clear_redraw(display)

    display.set_sync_mode(True)

    assert display._sync_on is True
    assert display._redraw is True


def test_setting_same_sync_mode_does_not_mark_redraw():
    display = make_display()
    display.set_sync_mode(True)
    clear_redraw(display)

    display.set_sync_mode(True)

    assert display._sync_on is True
    assert display._redraw is False


def test_set_rig_status_disconnected_when_no_socket():
    display = make_display()
    clear_redraw(display)

    display.set_rig(None, None)

    assert display._rig_freq is None
    assert display._rigctld_connected is None
    assert display._rig_status == "\033[31mDIS\033[0m"
    assert display._redraw is True


def test_set_rig_status_gray_when_rigctld_connected_but_rig_not_confirmed():
    display = make_display()
    clear_redraw(display)

    display.set_rig(14_200_000, object())

    assert display._rig_freq == 14_200_000
    assert display._rigctld_connected is not None
    assert display._rig_status == "CON"
    assert display._redraw is True


def test_set_rig_con_makes_rig_status_green_when_rigctld_is_connected():
    display = make_display()
    display.set_rig(14_200_000, object())
    clear_redraw(display)

    display.set_rig_con(True)

    assert display._rig_connected is True
    assert display._rig_status == "\033[32mCON\033[0m"
    assert display._redraw is True


def test_set_gqrx_status_and_frequency():
    display = make_display()
    clear_redraw(display)

    display.set_gqrx(14_200_000, True)

    assert display._gqrx_freq == 14_200_000
    assert display._gqrx_status == "\033[32mCON\033[0m"
    assert display._redraw is True


def test_input_setters_truncate_to_three_characters():
    display = make_display()

    display.set_keyboard_input("LONG")
    display.set_mouse_input("MOUSE")
    display.set_knob_input("KNOB")

    assert display._keyboard_input == "LON"
    assert display._mouse_input == "MOU"
    assert display._knob_input == "KNO"


def test_set_band_name_right_justifies_and_truncates():
    display = make_display()

    display.set_band_name("20m")
    assert display._band_name == "   20m"

    display.set_band_name("160m-A")
    assert display._band_name == "160m-A"

    display.set_band_name("160m-AB")
    assert display._band_name == "160m-A"


def test_log_keeps_full_display_line_limit():
    display = make_display()
    display.cfg.display.log_lines = 3

    display.log("one")
    display.log("two")
    display.log("three")
    display.log("four")

    assert [msg for msg, _ in display._logs] == ["four", "three", "two"]


def test_log_keeps_small_display_line_limit():
    display = make_display(small=True)
    display.cfg.display.log_lines_small = 1

    display.log("one")
    display.log("two")

    assert [msg for msg, _ in display._logs] == ["two"]


def test_log_uses_only_first_line():
    display = make_display()

    display.log("first\nsecond")

    assert display._logs[0][0] == "first"


def test_toggle_small_display_flips_flag_and_resets_layout_state():
    display = make_display()
    display._row_map = {"rig": 4, "gqrx": 5}
    display._last_log_end_row = 99
    clear_redraw(display)

    display.toggle_small_display()

    assert display.cfg.display.small_display is True
    assert display._row_map == {}
    assert display._last_log_end_row == 0
    assert display._redraw is True


def test_draw_clears_expired_logs(monkeypatch):
    display = make_display()
    display.cfg.display.log_drop_time = 1.0
    display._logs = [
        ("old", 8.0),
        ("new", 9.5),
    ]
    display._redraw = True

    written = []
    monkeypatch.setattr("sys.stdout.write", lambda text: written.append(text))
    monkeypatch.setattr("sys.stdout.flush", lambda: None)

    display.draw(now=10.0)

    assert [msg for msg, _ in display._logs] == ["new"]
    assert written


def test_draw_clears_stale_input_indicators(monkeypatch):
    display = make_display()
    display.cfg.display.input_drop_time = 1.0
    display._keyboard_input = "UP "
    display._mouse_input = "DWN"
    display._knob_input = "STP"
    display._keyboard_ts = 8.0
    display._mouse_ts = 8.0
    display._knob_ts = 8.0
    display._redraw = True

    monkeypatch.setattr("sys.stdout.write", lambda text: None)
    monkeypatch.setattr("sys.stdout.flush", lambda: None)

    display.draw(now=10.0)

    assert display._keyboard_input == "   "
    assert display._mouse_input == "   "
    assert display._knob_input == "   "