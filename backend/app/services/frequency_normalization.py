"""Conservative frequency normalization using the declared ADIF band.

ADIF defines FREQ in MHz, but a few exports have historically emitted GHz or
kHz-looking values while still declaring the correct BAND.  The declared band
is used only to repair an unambiguous factor-of-1000 unit error; raw ADIF data
is never modified.
"""
from __future__ import annotations

from typing import Any, Optional, Tuple


# Broad amateur allocations are intentional.  They validate the unit without
# rejecting valid regional sub-bands or satellite use near an allocation edge.
BAND_RANGES_MHZ = {
    "2190M": (0.135, 0.139),
    "630M": (0.470, 0.480),
    "160M": (1.8, 2.0),
    "80M": (3.5, 4.0),
    "60M": (5.0, 5.5),
    "40M": (7.0, 7.3),
    "30M": (10.1, 10.15),
    "20M": (14.0, 14.35),
    "17M": (18.068, 18.168),
    "15M": (21.0, 21.45),
    "12M": (24.89, 24.99),
    "10M": (28.0, 29.7),
    "6M": (50.0, 54.0),
    "4M": (69.5, 70.5),
    "2M": (144.0, 148.0),
    "1.25M": (219.0, 225.0),
    "70CM": (420.0, 450.0),
    "33CM": (902.0, 928.0),
    "23CM": (1240.0, 1300.0),
}


def _band_key(value: Any) -> str:
    return str(value or "").strip().upper().replace(" ", "")


def normalize_frequency_mhz(value: Any, band: Any) -> Tuple[Optional[float], bool]:
    """Return ``(MHz, corrected)`` for a safe, band-backed unit repair.

    Values already inside the declared band are preserved.  If the original is
    outside the band, only x1000 and /1000 are considered.  No correction is
    performed when BAND is absent or unknown.
    """
    if value in (None, ""):
        return None, False
    try:
        original = float(value)
    except (TypeError, ValueError):
        return None, False
    if original <= 0:
        return None, False

    limits = BAND_RANGES_MHZ.get(_band_key(band))
    if limits is None:
        return original, False
    low, high = limits
    if low <= original <= high:
        return original, False

    candidates = [candidate for candidate in (original * 1000.0, original / 1000.0) if low <= candidate <= high]
    if len(candidates) != 1:
        return original, False
    return candidates[0], True


def normalize_frequency_hz(value_hz: Any, band: Any) -> Tuple[Optional[int], bool]:
    """Normalize a frequency already stored in Hz using the declared band."""
    if value_hz in (None, ""):
        return None, False
    try:
        mhz = float(value_hz) / 1_000_000.0
    except (TypeError, ValueError):
        return None, False
    normalized, corrected = normalize_frequency_mhz(mhz, band)
    return (round(normalized * 1_000_000) if normalized is not None else None), corrected
