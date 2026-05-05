import pansyncer.bands as bands_module
from pansyncer.bands import Band, Bands
from pansyncer.bands import Bands


def test_band_name_inside_default_band():
    bands = Bands()

    assert bands.band_name(14.200) == " 20m"


def test_band_name_out_of_band():
    bands = Bands()

    assert bands.band_name(13.999) == "OOB"


def test_band_end_is_inclusive():
    bands = Bands()

    assert bands.band_name(14.350) == " 20m"


def test_band_step_up_from_inside_band():
    bands = Bands()

    assert bands.step(14.200, 1) == 18.120


def test_band_step_down_from_inside_band():
    bands = Bands()

    assert bands.step(14.200, -1) == 10.130


def test_band_step_remembers_last_position_inside_band():
    bands = Bands()

    assert bands.step(14.200, 1) == 18.120
    assert bands.step(18.120, -1) == 14.200
def test_band_start_is_inclusive():
    bands = Bands()

    assert bands.band_name(14.000) == " 20m"


def test_step_up_from_last_band_returns_false_and_beeps(monkeypatch):
    bands = Bands()
    beep_calls = []

    monkeypatch.setattr(bands_module, "beep", lambda: beep_calls.append("beep"))

    assert bands.step(50.100, 1) is False
    assert beep_calls == ["beep"]


def test_step_down_from_first_band_returns_false_and_beeps(monkeypatch):
    bands = Bands()
    beep_calls = []

    monkeypatch.setattr(bands_module, "beep", lambda: beep_calls.append("beep"))

    assert bands.step(1.843, -1) is False
    assert beep_calls == ["beep"]


def test_step_up_from_oob_below_first_band_goes_to_first_band():
    bands = Bands()

    assert bands.step(1.000, 1) == 1.843


def test_step_down_from_oob_below_first_band_returns_false_and_beeps(monkeypatch):
    bands = Bands()
    beep_calls = []

    monkeypatch.setattr(bands_module, "beep", lambda: beep_calls.append("beep"))

    assert bands.step(1.000, -1) is False
    assert beep_calls == ["beep"]


def test_step_up_from_oob_between_bands_goes_to_next_band():
    bands = Bands()

    assert bands.step(15.000, 1) == 18.120


def test_step_down_from_oob_between_bands_goes_to_previous_band():
    bands = Bands()

    assert bands.step(15.000, -1) == 14.125


def test_step_up_from_oob_above_last_band_returns_false_and_beeps(monkeypatch):
    bands = Bands()
    beep_calls = []

    monkeypatch.setattr(bands_module, "beep", lambda: beep_calls.append("beep"))

    assert bands.step(60.000, 1) is False
    assert beep_calls == ["beep"]


def test_step_down_from_oob_above_last_band_goes_to_last_band():
    bands = Bands()

    assert bands.step(60.000, -1) == 50.100


def test_bands_copy_source_band_objects_before_mutating_goto():
    source = [
        Band(" A", 1.0, 1.1, 2.0),
        Band(" B", 3.0, 3.1, 4.0),
    ]
    bands = Bands(source)

    assert bands.step(1.5, 1) == 3.1

    assert source[0].goto == 1.1

def test_bands_sorts_custom_band_source():
    source = [
        Band(" BBm", 3.0, 3.1, 3.2),
        Band(" AAm", 1.0, 1.1, 1.2),
    ]

    bands = Bands(source)

    assert bands.band_name(1.1) == " AAm"
    assert bands.band_name(3.1) == " BBm"


def test_bands_repairs_invalid_goto_to_midpoint_on_100_hz_grid():
    source = [
        Band(" XXm", 1.00005, 9.0, 1.00024),
    ]

    bands = Bands(source)

    assert bands.step(1.0001, 1) is False