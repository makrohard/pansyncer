"""
pansyncer bands.py
Ham radio band definitions and utilities
"""
from dataclasses import dataclass
from bisect import bisect_right
from pansyncer.utils import beep

@dataclass
class Band:
    name: str
    start: float
    goto: float
    end: float

DEFAULT_BANDS = [
    Band("160m",  1.810, 1.843, 2.000),
    Band(" 80m",  3.500, 3.603, 3.800),
    Band(" 60m",  5.3515, 5.354, 5.3665),
    Band(" 40m",  7.000, 7.053, 7.200),
    Band(" 30m", 10.100, 10.130, 10.150),
    Band(" 20m", 14.000, 14.125, 14.350),
    Band(" 17m", 18.068, 18.120, 18.168),
    Band(" 15m", 21.000, 21.151, 21.450),
    Band(" 12m", 24.890, 24.940, 24.990),
    Band(" 10m", 28.000, 28.320, 29.700),
    Band("  6m", 50.000, 50.100, 52.000),
]

class Bands:
    """ Band classifier """

    def __init__(self, bands=None):
        self._bands = bands or DEFAULT_BANDS
        self._starts = [b.start for b in self._bands]
        self._ends   = [b.end   for b in self._bands]

    def band_name(self, freq_mhz):
        idx = self._get_band_index(freq_mhz)
        return self._bands[idx].name if idx is not None else "OOB"

    def step(self, freq_mhz, direction):
        """Band Up / Down"""
        idx_inside = self._get_band_index(freq_mhz)
        if idx_inside is not None:
            if direction > 0:
                if idx_inside == len(self._bands) - 1:
                    beep()
                    return False
                self._bands[idx_inside].goto = freq_mhz
                return self._bands[idx_inside + 1].goto
            else:
                if idx_inside == 0:
                    beep()
                    return False
                self._bands[idx_inside].goto = freq_mhz
                return self._bands[idx_inside - 1].goto

        i = self._index_for(freq_mhz)
        if direction > 0:
            next_idx = i + 1
            if next_idx >= len(self._bands):
                beep()
                return False
            return self._bands[next_idx].goto
        else:
            if i < 0:
                beep()
                return False
            return self._bands[i].goto

    def _index_for(self, freq_mhz):
        return bisect_right(self._starts, freq_mhz) - 1

    def _get_band_index(self, freq_mhz):
        i = self._index_for(freq_mhz)
        if 0 <= i < len(self._bands) and freq_mhz <= self._ends[i]:
            return i
        return None
