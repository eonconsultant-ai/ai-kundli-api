"""Current transits mapped against a natal chart."""

from __future__ import annotations

from datetime import UTC, datetime

from .constants import PLANET_ORDER
from .ephemeris import ChartPositions, sidereal_positions
from .time import iso, to_julian_day


def _house_from(reference_sign: int, target_sign: int) -> int:
    return ((target_sign - reference_sign) % 12) + 1


def sade_sati(saturn_sign: int, natal_moon_sign: int) -> dict:
    offset = (saturn_sign - natal_moon_sign) % 12
    phases = {11: "first", 0: "peak", 1: "third"}
    if offset in phases:
        return {
            "active": True,
            "phase": phases[offset],
            "description": "Saturn is transiting the 12th, 1st or 2nd house from the natal Moon.",
        }
    return {"active": False, "phase": None, "description": None}


def compute_transits(
    natal: ChartPositions,
    *,
    latitude: float,
    longitude: float,
    ayanamsa: str = "lahiri",
    node_mode: str = "true",
    at: datetime | None = None,
) -> dict:
    moment = at or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    jd = to_julian_day(moment)
    current = sidereal_positions(
        jd,
        latitude,
        longitude,
        ayanamsa=ayanamsa,
        node_mode=node_mode,
    )

    moon_sign = natal.bodies["moon"].sign_index
    lagna_sign = natal.ascendant.sign_index
    planets = []
    for key in PLANET_ORDER:
        body = current.bodies[key]
        entry = body.as_dict()
        entry["house_from_moon"] = _house_from(moon_sign, body.sign_index)
        entry["house_from_lagna"] = _house_from(lagna_sign, body.sign_index)
        planets.append(entry)

    return {
        "as_of": iso(moment),
        "ayanamsa": ayanamsa,
        "planets": planets,
        "sade_sati": sade_sati(current.bodies["saturn"].sign_index, moon_sign),
    }
