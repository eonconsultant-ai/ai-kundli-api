"""Divisional chart (varga) sign mapping for the commonly used vargas."""

from __future__ import annotations

from .constants import PLANET_ORDER, SIGN_MODALITIES, SIGNS, VARGA_DIVISIONS, VARGA_NAMES
from .ephemeris import BodyPosition
from .time import AstroInputError


def varga_sign(longitude: float, divisions: int) -> int:
    """Return the 0-based sign index in a divisional chart."""
    if divisions not in (1, 3, 7, 9, 10, 12):
        raise AstroInputError(f"Unsupported varga division: D{divisions}")

    longitude %= 360
    sign = int(longitude // 30)
    degree_in_sign = longitude % 30
    part_span = 30 / divisions
    part = min(int(degree_in_sign / part_span), divisions - 1)

    if divisions == 1:
        return sign
    if divisions == 3:
        # 1st, 5th, 9th from the sign for the three decanates.
        return (sign + part * 4) % 12
    if divisions == 7:
        # Odd signs start from themselves; even signs from the 7th.
        start = sign if sign % 2 == 0 else (sign + 6) % 12
        return (start + part) % 12
    if divisions == 9:
        # Movable signs begin with themselves, fixed with the 9th, dual with
        # the 5th. This avoids float error at exact sign boundaries.
        modality = SIGN_MODALITIES[sign]
        start = sign if modality == "movable" else (sign + 8) % 12 if modality == "fixed" else (sign + 4) % 12
        return (start + part) % 12
    if divisions == 10:
        # Odd signs start from themselves; even signs from the 9th.
        start = sign if sign % 2 == 0 else (sign + 8) % 12
        return (start + part) % 12
    # D12: each 2.5-degree part starts from the sign itself.
    return (sign + part) % 12


def _sign_dict(sign_index: int) -> dict:
    sign = SIGNS[sign_index]
    return {
        "sign_index": sign_index,
        "sign": sign["name"],
        "sign_sanskrit": sign["sanskrit"],
    }


def build_vargas(
    bodies: dict[str, BodyPosition],
    ascendant_longitude: float,
    *,
    include: tuple[str, ...] = ("D1", "D3", "D7", "D9", "D10", "D12"),
) -> dict:
    charts: dict[str, dict] = {}
    for code in include:
        divisions = VARGA_DIVISIONS[code]
        asc_index = varga_sign(ascendant_longitude, divisions)
        planets = {}
        for key in PLANET_ORDER:
            body = bodies[key]
            varga_index = varga_sign(body.longitude, divisions)
            entry = {
                **_sign_dict(varga_index),
                "house": ((varga_index - asc_index) % 12) + 1,
                "retrograde": body.retrograde,
                "combust": body.combust,
            }
            if code in ("D1", "D9"):
                entry["vargottama"] = body.sign_index == varga_sign(body.longitude, 9)
            planets[key] = entry

        charts[code] = {
            "name": VARGA_NAMES[code],
            "divisions": divisions,
            "ascendant": {
                **_sign_dict(asc_index),
                "house": 1,
            },
            "planets": planets,
        }
    return charts
