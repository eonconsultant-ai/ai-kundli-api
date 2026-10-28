"""Daily Panchang elements, sunrise/sunset and inauspicious daytime windows."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import swisseph as swe

from .constants import (
    GULIKA_SEGMENT,
    KARANA_MOVABLE,
    NAKSHATRA_SPAN,
    RAHU_SEGMENT,
    TITHI_NAMES,
    WEEKDAYS,
    YAMAGANDA_SEGMENT,
    YOGA_NAMES,
)
from .ephemeris import ChartPositions, sidereal_positions
from .time import (
    AstroInputError,
    iso,
    julian_day_to_local,
    julian_day_to_utc,
    local_midnight_jd,
    to_julian_day,
)

_SHADOW_SEGMENTS = {
    "rahu": RAHU_SEGMENT,
    "gulika": GULIKA_SEGMENT,
    "yamaganda": YAMAGANDA_SEGMENT,
}


def _rise_or_set(jd_start: float, event: int, latitude: float, longitude: float, altitude_m: float) -> float | None:
    # Upper limb with standard refraction, matching Drik Panchang and most
    # printed panchangs. (Swiss Ephemeris calls the centre/no-refraction
    # variant "Hindu sunrise"; it differs by several minutes.)
    result, times = swe.rise_trans(
        jd_start,
        swe.SUN,
        event,
        (longitude, latitude, altitude_m),
        0,
        0,
        swe.FLG_SWIEPH,
    )
    if result != 0:
        return None
    return float(times[0])


def sunrise_sunset(
    day: date,
    latitude: float,
    longitude: float,
    tz_name: str,
    altitude_m: float = 0.0,
) -> tuple[float, float]:
    start_jd = local_midnight_jd(day, tz_name)
    sunrise = _rise_or_set(start_jd, swe.CALC_RISE, latitude, longitude, altitude_m)
    if sunrise is None:
        raise AstroInputError("No sunrise occurs for this location and date.")
    sunset = _rise_or_set(sunrise, swe.CALC_SET, latitude, longitude, altitude_m)
    if sunset is None:
        raise AstroInputError("No sunset occurs for this location and date.")

    sunrise_date = julian_day_to_local(sunrise, tz_name).date()
    if sunrise_date != day:
        raise AstroInputError(f"Sunrise search crossed into {sunrise_date.isoformat()}.")
    return sunrise, sunset


def _weekday_index(day: date) -> int:
    return (day.weekday() + 1) % 7


def _tithi(sun_longitude: float, moon_longitude: float) -> dict:
    difference = (moon_longitude - sun_longitude) % 360
    number = int(difference // 12) + 1
    name_index = (number - 1) % 15
    if number == 15:
        name = "Purnima"
    elif number == 30:
        name = "Amavasya"
    else:
        name = TITHI_NAMES[name_index]
    return {
        "number": number,
        "paksha": "shukla" if number <= 15 else "krishna",
        "name": name,
        "progress": round((difference % 12) / 12, 6),
    }


def _yoga(sun_longitude: float, moon_longitude: float) -> dict:
    value = (sun_longitude + moon_longitude) % 360
    index = int(value // NAKSHATRA_SPAN) % 27
    return {
        "number": index + 1,
        "name": YOGA_NAMES[index],
        "progress": round((value % NAKSHATRA_SPAN) / NAKSHATRA_SPAN, 6),
    }


def _karana(sun_longitude: float, moon_longitude: float) -> dict:
    difference = (moon_longitude - sun_longitude) % 360
    index = int(difference // 6) % 60
    if index == 0:
        name = "Kimstughna"
    elif index <= 56:
        name = KARANA_MOVABLE[(index - 1) % 7]
    else:
        name = {57: "Shakuni", 58: "Chatushpada", 59: "Naga"}[index]
    return {"number": index + 1, "name": name}


def lunar_element(elements_positions: ChartPositions) -> dict:
    sun = elements_positions.bodies["sun"]
    moon = elements_positions.bodies["moon"]
    return {
        "tithi": _tithi(sun.longitude, moon.longitude),
        "nakshatra": {
            "index": moon.nakshatra_index,
            "number": moon.nakshatra_index + 1,
            "name": moon.nakshatra,
            "lord": moon.nakshatra_lord,
            "pada": moon.pada,
        },
        "yoga": _yoga(sun.longitude, moon.longitude),
        "karana": _karana(sun.longitude, moon.longitude),
    }


def daily_panchang(
    day: date,
    latitude: float,
    longitude: float,
    tz_name: str,
    *,
    altitude_m: float = 0.0,
    ayanamsa: str = "lahiri",
    node_mode: str = "true",
) -> dict:
    sunrise_jd, sunset_jd = sunrise_sunset(day, latitude, longitude, tz_name, altitude_m)
    positions = sidereal_positions(
        sunrise_jd,
        latitude,
        longitude,
        ayanamsa=ayanamsa,
        node_mode=node_mode,
    )
    elements = lunar_element(positions)

    sunrise_local = julian_day_to_local(sunrise_jd, tz_name)
    sunset_local = julian_day_to_local(sunset_jd, tz_name)
    weekday_index = _weekday_index(sunrise_local.date())
    weekday = WEEKDAYS[weekday_index]

    day_seconds = (sunset_jd - sunrise_jd) * 86400
    segment_seconds = day_seconds / 8
    sunrise_utc = julian_day_to_utc(sunrise_jd)
    tz = ZoneInfo(tz_name)

    def segment_window(segment: int) -> dict:
        start = sunrise_utc + timedelta(seconds=segment_seconds * (segment - 1))
        end = sunrise_utc + timedelta(seconds=segment_seconds * segment)
        return {
            "start": iso(start.astimezone(tz)),
            "end": iso(end.astimezone(tz)),
        }

    return {
        "date": day.isoformat(),
        "location": {
            "latitude": latitude,
            "longitude": longitude,
            "timezone": tz_name,
            "altitude_m": altitude_m,
        },
        "reference": "sunrise",
        "reference_time": iso(sunrise_local),
        "sunrise": iso(sunrise_local),
        "sunset": iso(sunset_local),
        "day_duration_minutes": round(day_seconds / 60, 2),
        "vara": {
            "index": weekday_index,
            "name": weekday["name"],
            "sanskrit": weekday["sanskrit"],
        },
        **elements,
        "kaal": {
            "rahu": segment_window(RAHU_SEGMENT[weekday_index]),
            "gulika": segment_window(GULIKA_SEGMENT[weekday_index]),
            "yamaganda": segment_window(YAMAGANDA_SEGMENT[weekday_index]),
        },
        "moon_sign": positions.bodies["moon"].sign,
        "sun_sign": positions.bodies["sun"].sign,
    }


def panchang_at_instant(
    instant_utc: datetime,
    positions: ChartPositions,
    tz_name: str,
) -> dict:
    """Lunar Panchang elements at a specific instant, used for birth Panchang."""
    local = instant_utc.astimezone(ZoneInfo(tz_name))
    weekday_index = _weekday_index(local.date())
    weekday = WEEKDAYS[weekday_index]
    return {
        "reference": "birth_instant",
        "reference_time": iso(local),
        "vara": {
            "index": weekday_index,
            "name": weekday["name"],
            "sanskrit": weekday["sanskrit"],
        },
        **lunar_element(positions),
    }


def ayanamsa_at(jd_ut: float) -> float:
    return swe.get_ayanamsa_ut(jd_ut)


def julian_day_now() -> float:
    return to_julian_day(datetime.now(UTC))
