"""Assemble a complete Kundli response from the calculation modules."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any

from .constants import (
    DASHA_YEAR_DAYS,
    PLANET_ORDER,
)
from .dasha import vimshottari
from .ephemeris import ChartPositions, sidereal_positions
from .panchang import panchang_at_instant
from .time import iso, resolve_local_moment, to_julian_day
from .transit import compute_transits
from .varga import build_vargas, varga_sign

ENGINE_NAME = "jyotish-engine"
ENGINE_VERSION = "0.1.0"
MANGLIK_HOUSES = (1, 2, 4, 7, 8, 12)


def mangal_dosha(positions: ChartPositions) -> dict:
    mars = positions.bodies["mars"]
    moon_sign = positions.bodies["moon"].sign_index
    venus_sign = positions.bodies["venus"].sign_index
    lagna_sign = positions.ascendant.sign_index
    mars_sign = mars.sign_index

    references = {
        "lagna": (mars.house, lagna_sign),
        "moon": (((mars_sign - moon_sign) % 12) + 1, moon_sign),
        "venus": (((mars_sign - venus_sign) % 12) + 1, venus_sign),
    }
    active_from = [name for name, (house, _) in references.items() if house in MANGLIK_HOUSES]

    return {
        "is_manglik": bool(active_from),
        "active_from": active_from,
        "mars_house_from_lagna": references["lagna"][0],
        "mars_house_from_moon": references["moon"][0],
        "mars_house_from_venus": references["venus"][0],
        "houses_checked": list(MANGLIK_HOUSES),
        "note": (
            "Mangal Dosha is assessed here from the Lagna, Moon and Venus. "
            "Classical cancellation rules differ by lineage and are not applied."
        ),
    }


def _vargottama(positions: ChartPositions) -> list[str]:
    names: list[str] = []
    for key in PLANET_ORDER:
        body = positions.bodies[key]
        if body.sign_index == varga_sign(body.longitude, 9):
            names.append(key)
    return names


def build_kundli(
    *,
    birth_date: date,
    birth_time: time,
    tz_name: str,
    latitude: float,
    longitude: float,
    name: str | None = None,
    place_name: str | None = None,
    altitude_m: float = 0.0,
    ayanamsa: str = "lahiri",
    node_mode: str = "true",
    include_pratyantar: bool = True,
    transit_at: datetime | None = None,
) -> dict[str, Any]:
    resolved = resolve_local_moment(birth_date, birth_time, tz_name)
    jd = to_julian_day(resolved.utc)

    positions = sidereal_positions(
        jd,
        latitude,
        longitude,
        ayanamsa=ayanamsa,
        node_mode=node_mode,
    )
    vargas = build_vargas(positions.bodies, positions.ascendant.longitude)
    dashas = vimshottari(
        positions.bodies["moon"].longitude,
        resolved.utc,
        tz_name,
        include_pratyantar=include_pratyantar,
    )
    birth_panchang = panchang_at_instant(resolved.utc, positions, tz_name)
    transits = compute_transits(
        positions,
        latitude=latitude,
        longitude=longitude,
        ayanamsa=ayanamsa,
        node_mode=node_mode,
        at=transit_at,
    )

    moon = positions.bodies["moon"]
    sun = positions.bodies["sun"]
    ascendant = positions.ascendant

    return {
        "subject": {
            "name": name,
            "birth_date": birth_date.isoformat(),
            "birth_time": birth_time.isoformat(),
            "timezone": tz_name,
            "utc_offset_seconds": int(resolved.local.utcoffset().total_seconds()),
            "place_name": place_name,
            "latitude": latitude,
            "longitude": longitude,
            "altitude_m": altitude_m,
            "birth_utc": iso(resolved.utc),
        },
        "lagna": ascendant.as_dict(),
        "moon_sign": {
            "index": moon.sign_index,
            "sign": moon.sign,
            "sanskrit": moon.sign_sanskrit,
            "nakshatra": moon.nakshatra,
            "pada": moon.pada,
        },
        "sun_sign": {
            "index": sun.sign_index,
            "sign": sun.sign,
            "sanskrit": sun.sign_sanskrit,
        },
        "panchang_at_birth": birth_panchang,
        "planets": [positions.bodies[key].as_dict() for key in PLANET_ORDER],
        "houses": list(positions.houses),
        "vargas": vargas,
        "vargottama": _vargottama(positions),
        "dashas": dashas,
        "transits": transits,
        "mangal_dosha": mangal_dosha(positions),
        "engine": {
            "name": ENGINE_NAME,
            "version": ENGINE_VERSION,
            "ephemeris": positions.ephemeris,
            "ayanamsa": ayanamsa,
            "ayanamsa_value": round(positions.ayanamsa_value, 6),
            "node_mode": node_mode,
            "house_system": "whole_sign",
            "dasha_year_days": DASHA_YEAR_DAYS,
            "computed_at": iso(datetime.now(UTC)),
            "warnings": list(resolved.warnings),
        },
        "disclaimer": (
            "Astrological calculations are provided for guidance and entertainment. "
            "They are not medical, legal or financial advice."
        ),
    }
