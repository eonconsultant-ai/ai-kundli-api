"""Sidereal planetary positions, ascendant and whole-sign houses."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import swisseph as swe

from .constants import (
    COMBUSTION_ORBS,
    NAKSHATRA_SPAN,
    NAKSHATRAS,
    PADA_SPAN,
    PLANET_META,
    PLANET_ORDER,
    SIGNS,
)
from .time import AstroInputError

_SID_MODE = {
    "lahiri": swe.SIDM_LAHIRI,
    "raman": swe.SIDM_RAMAN,
    "krishnamurti": swe.SIDM_KRISHNAMURTI,
    "true_citra": swe.SIDM_TRUE_CITRA,
}

_NODE_MODE = {
    "true": swe.TRUE_NODE,
    "mean": swe.MEAN_NODE,
}

# Swiss Ephemeris keeps sidereal mode and ephemeris path in process-global state.
# This service is CPU-bound and cheap per chart; a lock is preferable to subtle races.
_COMPUTE_LOCK = threading.Lock()


def configure_ephemeris(ephe_path: str | Path) -> None:
    path = Path(ephe_path)
    path.mkdir(parents=True, exist_ok=True)
    with _COMPUTE_LOCK:
        swe.set_ephe_path(str(path))


@dataclass(frozen=True)
class BodyPosition:
    key: str
    name: str
    sanskrit: str
    longitude: float
    speed: float
    sign_index: int
    sign: str
    sign_sanskrit: str
    degree_in_sign: float
    degree_dms: str
    nakshatra_index: int
    nakshatra: str
    nakshatra_lord: str
    pada: int
    retrograde: bool
    combust: bool
    house: int

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "sanskrit": self.sanskrit,
            "longitude": round(self.longitude, 6),
            "speed": round(self.speed, 6),
            "sign_index": self.sign_index,
            "sign": self.sign,
            "sign_sanskrit": self.sign_sanskrit,
            "degree_in_sign": round(self.degree_in_sign, 4),
            "degree_dms": self.degree_dms,
            "nakshatra_index": self.nakshatra_index,
            "nakshatra": self.nakshatra,
            "nakshatra_lord": self.nakshatra_lord,
            "pada": self.pada,
            "retrograde": self.retrograde,
            "combust": self.combust,
            "house": self.house,
        }


@dataclass(frozen=True)
class Ascendant:
    longitude: float
    sign_index: int
    sign: str
    sign_sanskrit: str
    degree_in_sign: float
    degree_dms: str
    nakshatra: str
    pada: int

    def as_dict(self) -> dict:
        return {
            "longitude": round(self.longitude, 6),
            "sign_index": self.sign_index,
            "sign": self.sign,
            "sign_sanskrit": self.sign_sanskrit,
            "degree_in_sign": round(self.degree_in_sign, 4),
            "degree_dms": self.degree_dms,
            "nakshatra": self.nakshatra,
            "pada": self.pada,
            "house": 1,
        }


@dataclass(frozen=True)
class ChartPositions:
    bodies: dict[str, BodyPosition]
    ascendant: Ascendant
    houses: tuple[dict, ...]
    ayanamsa_value: float
    ephemeris: str
    node_mode: str

    def as_dict(self) -> dict:
        return {
            "ascendant": self.ascendant.as_dict(),
            "planets": [self.bodies[key].as_dict() for key in PLANET_ORDER],
            "houses": list(self.houses),
        }


def _dms(longitude: float) -> str:
    deg = int(longitude)
    minutes_float = (longitude - deg) * 60
    minutes = int(minutes_float)
    seconds = int(round((minutes_float - minutes) * 60))
    if seconds == 60:
        seconds = 0
        minutes += 1
    if minutes == 60:
        minutes = 0
        deg += 1
    return f"{deg}°{minutes:02d}'{seconds:02d}\""


def _sign(longitude: float) -> tuple[int, str, str, float]:
    sign_index = int(longitude // 30) % 12
    sign = SIGNS[sign_index]
    return sign_index, sign["name"], sign["sanskrit"], longitude % 30


def _nakshatra(longitude: float) -> tuple[int, str, str, int]:
    index = int(longitude / NAKSHATRA_SPAN) % 27
    pada = int((longitude % NAKSHATRA_SPAN) / PADA_SPAN) + 1
    nak = NAKSHATRAS[index]
    return index, str(nak["name"]), str(nak["lord"]), min(pada, 4)


def _angular_separation(first: float, second: float) -> float:
    return abs((first - second + 180) % 360 - 180)


def _compute_body(
    key: str,
    longitude: float,
    speed: float,
    asc_sign_index: int,
    sun_longitude: float | None,
) -> BodyPosition:
    sign_index, sign, sign_sanskrit, degree = _sign(longitude)
    nak_index, nak_name, nak_lord, pada = _nakshatra(longitude)

    retrograde = key in ("rahu", "ketu") or speed < 0
    combust = False
    if sun_longitude is not None and key in COMBUSTION_ORBS:
        direct_orb, retro_orb = COMBUSTION_ORBS[key]
        orb = retro_orb if retrograde else direct_orb
        combust = key != "sun" and _angular_separation(longitude, sun_longitude) <= orb

    meta = PLANET_META[key]
    return BodyPosition(
        key=key,
        name=meta["name"],
        sanskrit=meta["sanskrit"],
        longitude=longitude % 360,
        speed=speed,
        sign_index=sign_index,
        sign=sign,
        sign_sanskrit=sign_sanskrit,
        degree_in_sign=degree,
        degree_dms=_dms(degree),
        nakshatra_index=nak_index,
        nakshatra=nak_name,
        nakshatra_lord=nak_lord,
        pada=pada,
        retrograde=retrograde,
        combust=combust,
        house=((sign_index - asc_sign_index) % 12) + 1,
    )


def sidereal_positions(
    jd_ut: float,
    latitude: float,
    longitude: float,
    *,
    ayanamsa: str = "lahiri",
    node_mode: str = "true",
) -> ChartPositions:
    if ayanamsa not in _SID_MODE:
        raise AstroInputError(f"Unsupported ayanamsa: {ayanamsa}")
    if node_mode not in _NODE_MODE:
        raise AstroInputError(f"Unsupported node mode: {node_mode}")

    flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL | swe.FLG_SPEED

    with _COMPUTE_LOCK:
        swe.set_sid_mode(_SID_MODE[ayanamsa], 0, 0)
        try:
            sun_raw, sun_retflags = swe.calc_ut(jd_ut, swe.SUN, flags)
            moon_raw, _ = swe.calc_ut(jd_ut, swe.MOON, flags)
            rahu_raw, _ = swe.calc_ut(jd_ut, _NODE_MODE[node_mode], flags)
            planetary_raw = {
                key: swe.calc_ut(
                    jd_ut,
                    {
                        "mars": swe.MARS,
                        "mercury": swe.MERCURY,
                        "jupiter": swe.JUPITER,
                        "venus": swe.VENUS,
                        "saturn": swe.SATURN,
                    }[key],
                    flags,
                )
                for key in ("mars", "mercury", "jupiter", "venus", "saturn")
            }
            _cusps, ascmc = swe.houses_ex(
                jd_ut,
                latitude,
                longitude,
                b"P",
                swe.FLG_SWIEPH | swe.FLG_SIDEREAL,
            )
            ayanamsa_value = swe.get_ayanamsa_ut(jd_ut)
        except swe.Error as exc:
            raise AstroInputError(f"Ephemeris calculation failed: {exc}") from exc

    ephemeris = "moshier" if sun_retflags & swe.FLG_MOSEPH else "swiss"

    asc_longitude = ascmc[0] % 360
    asc_sign_index, asc_sign, asc_sanskrit, asc_degree = _sign(asc_longitude)
    asc_nak_index, asc_nak, _, asc_pada = _nakshatra(asc_longitude)

    raw_longitudes: dict[str, tuple[float, float]] = {
        "sun": (sun_raw[0], sun_raw[3]),
        "moon": (moon_raw[0], moon_raw[3]),
        "mars": (planetary_raw["mars"][0][0], planetary_raw["mars"][0][3]),
        "mercury": (planetary_raw["mercury"][0][0], planetary_raw["mercury"][0][3]),
        "jupiter": (planetary_raw["jupiter"][0][0], planetary_raw["jupiter"][0][3]),
        "venus": (planetary_raw["venus"][0][0], planetary_raw["venus"][0][3]),
        "saturn": (planetary_raw["saturn"][0][0], planetary_raw["saturn"][0][3]),
        "rahu": (rahu_raw[0], rahu_raw[3]),
        "ketu": ((rahu_raw[0] + 180) % 360, rahu_raw[3]),
    }

    bodies = {
        key: _compute_body(
            key,
            raw_longitudes[key][0],
            raw_longitudes[key][1],
            asc_sign_index,
            raw_longitudes["sun"][0],
        )
        for key in PLANET_ORDER
    }

    houses = tuple(
        {
            "house": number,
            "sign_index": (asc_sign_index + number - 1) % 12,
            "sign": SIGNS[(asc_sign_index + number - 1) % 12]["name"],
            "sign_sanskrit": SIGNS[(asc_sign_index + number - 1) % 12]["sanskrit"],
            "cusp_longitude": round((((asc_sign_index + number - 1) % 12) * 30) % 360, 6),
        }
        for number in range(1, 13)
    )

    ascendant = Ascendant(
        longitude=asc_longitude,
        sign_index=asc_sign_index,
        sign=asc_sign,
        sign_sanskrit=asc_sanskrit,
        degree_in_sign=asc_degree,
        degree_dms=_dms(asc_degree),
        nakshatra=asc_nak,
        pada=min(asc_pada, 4),
    )

    return ChartPositions(
        bodies=bodies,
        ascendant=ascendant,
        houses=houses,
        ayanamsa_value=ayanamsa_value,
        ephemeris=ephemeris,
        node_mode=node_mode,
    )
