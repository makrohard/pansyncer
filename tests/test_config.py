import pytest
from types import SimpleNamespace

from pansyncer.config import Config
from types import SimpleNamespace

from pansyncer.config import Config


def make_args(config_file, **overrides):
    values = {
        "config_file": str(config_file),
        "devices": None,
        "rig_port": None,
        "gqrx_port": None,
        "ifreq": None,
        "no_auto_rig": None,
        "freq_log_path": None,
        "small_display": None,
        "daemon": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def write_config(tmp_path, text):
    path = tmp_path / "pansyncer.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_config_file_uses_defaults(tmp_path):
    args = make_args(tmp_path / "missing.toml")

    cfg = Config.from_args_and_file(args)

    assert cfg.main.daemon is False
    assert cfg.main.ifreq is None
    assert cfg.main.no_auto_rig is False
    assert cfg.main.interval == 0.1
    assert cfg.sync.rig_port == 4532
    assert cfg.sync.gqrx_port == 7356
    assert cfg.display.small_display is False
    assert "rig" in cfg.devices.enabled
    assert "gqrx" in cfg.devices.enabled


def test_toml_overlays_defaults(tmp_path):
    config_path = write_config(
        tmp_path,
        """
[main]
daemon = true
ifreq = 73.095
interval = 0.2
no_auto_rig = true

[sync]
rig_port = 1234
gqrx_port = 5678
freq_log_path = "freq.log"

[display]
small_display = true
log_lines = 3

[devices]
enabled = ["rig", "gqrx"]
""",
    )
    args = make_args(config_path)

    cfg = Config.from_args_and_file(args)

    assert cfg.main.daemon is True
    assert cfg.main.ifreq == 73.095
    assert cfg.main.interval == 0.2
    assert cfg.main.no_auto_rig is True
    assert cfg.sync.rig_port == 1234
    assert cfg.sync.gqrx_port == 5678
    assert cfg.sync.freq_log_path == "freq.log"
    assert cfg.display.small_display is True
    assert cfg.display.log_lines == 3
    assert cfg.devices.enabled == ["rig", "gqrx"]


def test_cli_values_overlay_toml_when_not_none(tmp_path):
    config_path = write_config(
        tmp_path,
        """
[main]
daemon = false
ifreq = 70.000
no_auto_rig = false

[sync]
rig_port = 1111
gqrx_port = 2222
freq_log_path = "from_toml.log"

[display]
small_display = false

[devices]
enabled = ["rig"]
""",
    )
    args = make_args(
        config_path,
        daemon=True,
        ifreq=73.095,
        no_auto_rig=True,
        rig_port=3333,
        gqrx_port=4444,
        freq_log_path="from_cli.log",
        small_display=True,
        devices=["g"],
    )

    cfg = Config.from_args_and_file(args)

    assert cfg.main.daemon is True
    assert cfg.main.ifreq == 73.095
    assert cfg.main.no_auto_rig is True
    assert cfg.sync.rig_port == 3333
    assert cfg.sync.gqrx_port == 4444
    assert cfg.sync.freq_log_path == "from_cli.log"
    assert cfg.display.small_display is True
    assert cfg.devices.enabled == ["gqrx"]


def test_cli_none_values_do_not_overlay_toml(tmp_path):
    config_path = write_config(
        tmp_path,
        """
[main]
daemon = true
ifreq = 73.095
no_auto_rig = true

[sync]
rig_port = 1111
gqrx_port = 2222
freq_log_path = "from_toml.log"

[display]
small_display = true

[devices]
enabled = ["rig"]
""",
    )
    args = make_args(config_path)

    cfg = Config.from_args_and_file(args)

    assert cfg.main.daemon is True
    assert cfg.main.ifreq == 73.095
    assert cfg.main.no_auto_rig is True
    assert cfg.sync.rig_port == 1111
    assert cfg.sync.gqrx_port == 2222
    assert cfg.sync.freq_log_path == "from_toml.log"
    assert cfg.display.small_display is True
    assert cfg.devices.enabled == ["rig"]


def test_cli_device_short_names_are_mapped(tmp_path):
    args = make_args(
        tmp_path / "missing.toml",
        devices=["r", "g", "k", "m"],
    )

    cfg = Config.from_args_and_file(args)

    assert cfg.devices.enabled == ["rig", "gqrx", "knob", "mouse"]


def test_cli_device_long_names_are_kept(tmp_path):
    args = make_args(
        tmp_path / "missing.toml",
        devices=["rig", "gqrx", "knob", "mouse"],
    )

    cfg = Config.from_args_and_file(args)

    assert cfg.devices.enabled == ["rig", "gqrx", "knob", "mouse"]


def test_toml_band_region_is_loaded(tmp_path):
    config_path = write_config(
        tmp_path,
        """
[bands]
region = "test"

test = [
  { name = " XXm", start = 1.000, goto = 1.500, end = 2.000 }
]
""",
    )
    args = make_args(config_path)

    cfg = Config.from_args_and_file(args)

    assert len(cfg.bands) == 1
    assert cfg.bands[0].name == " XXm"
    assert cfg.bands[0].start == 1.000
    assert cfg.bands[0].goto == 1.500
    assert cfg.bands[0].end == 2.000


def test_unknown_toml_band_region_falls_back_to_default_bands(tmp_path):
    config_path = write_config(
        tmp_path,
        """
[bands]
region = "does_not_exist"

r1 = [
  { name = " XXm", start = 1.000, goto = 1.500, end = 2.000 }
]
""",
    )
    args = make_args(config_path)

    cfg = Config.from_args_and_file(args)

    assert len(cfg.bands) > 1
    assert any(band.name == " 20m" for band in cfg.bands)


def test_toml_knob_entries_are_loaded(tmp_path):
    config_path = write_config(
        tmp_path,
        """
[[knobs]]
target_name = "Test Knob"
target_vendor = 0x1234
target_product = 0x5678
key_up = 10
key_down = 11
key_step = 12
""",
    )
    args = make_args(config_path)

    cfg = Config.from_args_and_file(args)

    assert len(cfg.knobs) == 1
    assert cfg.knobs[0].target_name == "Test Knob"
    assert cfg.knobs[0].target_vendor == 0x1234
    assert cfg.knobs[0].target_product == 0x5678
    assert cfg.knobs[0].key_up == 10
    assert cfg.knobs[0].key_down == 11
    assert cfg.knobs[0].key_step == 12

def test_invalid_toml_exits_with_config_error(tmp_path, capsys):
    config_path = tmp_path / "broken.toml"
    config_path.write_text(
        """
[main
daemon = true
""",
        encoding="utf-8",
    )
    args = make_args(config_path)

    with pytest.raises(SystemExit) as excinfo:
        Config.from_args_and_file(args)

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "[CONFIG ERROR] Invalid TOML FILE" in captured.err
    assert str(config_path) in captured.err

    def assert_config_error_2(config_path, capsys):
        args = make_args(config_path)

        with pytest.raises(SystemExit) as excinfo:
            Config.from_args_and_file(args)

        assert excinfo.value.code == 2
        captured = capsys.readouterr()
        assert "[CONFIG ERROR]" in captured.err

    def test_toml_unsorted_band_entries_are_sorted(tmp_path):
        config_path = write_config(
            tmp_path,
            """
    [bands]
    region = "test"

    test = [
      { name = " BBm", start = 3.000, goto = 3.100, end = 3.200 },
      { name = " AAm", start = 1.000, goto = 1.100, end = 1.200 }
    ]
    """,
        )
        args = make_args(config_path)

        cfg = Config.from_args_and_file(args)

        assert [band.name for band in cfg.bands] == [" AAm", " BBm"]
        assert [band.start for band in cfg.bands] == [1.000, 3.000]

    def test_toml_band_goto_outside_range_is_repaired_to_midpoint_on_100_hz_grid(tmp_path):
        config_path = write_config(
            tmp_path,
            """
    [bands]
    region = "test"

    test = [
      { name = " XXm", start = 1.00005, goto = 9.000, end = 1.00024 }
    ]
    """,
        )
        args = make_args(config_path)

        cfg = Config.from_args_and_file(args)

        assert cfg.bands[0].goto == 1.0001

    def test_toml_band_missing_goto_is_repaired_to_midpoint_on_100_hz_grid(tmp_path):
        config_path = write_config(
            tmp_path,
            """
    [bands]
    region = "test"

    test = [
      { name = " XXm", start = 1.00005, end = 1.00024 }
    ]
    """,
        )
        args = make_args(config_path)

        cfg = Config.from_args_and_file(args)

        assert cfg.bands[0].goto == 1.0001

    def test_toml_band_entry_missing_required_field_exits_with_config_error(tmp_path, capsys):
        config_path = write_config(
            tmp_path,
            """
    [bands]
    region = "test"

    test = [
      { name = " XXm", goto = 1.500, end = 2.000 }
    ]
    """,
        )

        assert_config_error_2(config_path, capsys)

    def test_toml_band_entry_invalid_range_exits_with_config_error(tmp_path, capsys):
        config_path = write_config(
            tmp_path,
            """
    [bands]
    region = "test"

    test = [
      { name = " XXm", start = 2.000, goto = 1.500, end = 1.000 }
    ]
    """,
        )

        assert_config_error_2(config_path, capsys)

    def test_toml_band_entries_must_not_overlap_exits_with_config_error(tmp_path, capsys):
        config_path = write_config(
            tmp_path,
            """
    [bands]
    region = "test"

    test = [
      { name = " AAm", start = 1.000, goto = 1.100, end = 2.000 },
      { name = " BBm", start = 1.900, goto = 2.100, end = 2.200 }
    ]
    """,
        )

        assert_config_error_2(config_path, capsys)