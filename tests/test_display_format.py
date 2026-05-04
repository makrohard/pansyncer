import pytest

from pansyncer.display import Display


@pytest.mark.parametrize(
    ("freq", "expected"),
    [
        (None, "          "),
        (0, "         0"),
        (1, "         1"),
        (100, "       100"),
        (999, "       999"),
        (1_000, "     1.000"),
        (14_200_000, "14.200.000"),
        (144_800_000, "144.800.000"),
        (1_234_567_890, "1.234.567.890"),
        (-100, "      -100"),
    ],
)
def test_fmt_hz_formats_frequency_values(freq, expected):
    assert Display._fmt_hz(freq) == expected


def test_fmt_hz_truncates_float_to_int():
    assert Display._fmt_hz(14_200_000.9) == "14.200.000"