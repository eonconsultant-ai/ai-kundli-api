"""Timezone-safe birth moment handling and Julian-day conversion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import swisseph as swe


class AstroInputError(ValueError):
    """Raised when birth data cannot be resolved into a unique instant."""


@dataclass(frozen=True)
class ResolvedMoment:
    utc: datetime
    local: datetime
    tz_name: str
    warnings: tuple[str, ...]


def resolve_local_moment(birth_date: date, birth_time: time, tz_name: str) -> ResolvedMoment:
    """Resolve a civil birth time to UTC using the IANA timezone database.

    Historical Indian offsets, including the 1942-1945 daylight-saving period,
    are handled by tzdata rather than by a fixed +05:30 assumption.
    """
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise AstroInputError(f"Unknown IANA timezone: {tz_name}") from exc

    naive_local = datetime.combine(birth_date, birth_time)
    candidate = naive_local.replace(tzinfo=tz)
    utc = candidate.astimezone(UTC)
    warnings: list[str] = []

    round_trip = utc.astimezone(tz).replace(tzinfo=None)
    if round_trip != naive_local:
        # A spring-forward gap: this civil time never existed. Fold 0 is the
        # conventional interpretation, but the user must be warned.
        utc = naive_local.replace(tzinfo=tz, fold=0).astimezone(UTC)
        warnings.append("Birth time falls in a daylight-saving gap; the pre-transition offset was used.")
    else:
        fold_0 = naive_local.replace(tzinfo=tz, fold=0).astimezone(UTC)
        fold_1 = naive_local.replace(tzinfo=tz, fold=1).astimezone(UTC)
        if fold_0 != fold_1:
            warnings.append("Birth time is ambiguous due to a clock rollback; fold 0 was used.")

    local = utc.astimezone(tz)
    return ResolvedMoment(utc=utc, local=local, tz_name=tz_name, warnings=tuple(warnings))


def to_julian_day(moment: datetime) -> float:
    if moment.tzinfo is None:
        raise AstroInputError("Julian day conversion requires a timezone-aware datetime.")
    utc = moment.astimezone(UTC)
    hour = utc.hour + utc.minute / 60 + (utc.second + utc.microsecond / 1_000_000) / 3600
    return swe.julday(utc.year, utc.month, utc.day, hour, swe.GREG_CAL)


def julian_day_to_utc(jd_ut: float) -> datetime:
    year, month, day, hour = swe.revjul(jd_ut, swe.GREG_CAL)
    seconds = round(hour * 3600, 3)
    return datetime(year, month, day, tzinfo=UTC) + timedelta(seconds=seconds)


def julian_day_to_local(jd_ut: float, tz_name: str) -> datetime:
    return julian_day_to_utc(jd_ut).astimezone(ZoneInfo(tz_name))


def local_midnight_jd(day: date, tz_name: str) -> float:
    midnight = datetime.combine(day, time.min, tzinfo=ZoneInfo(tz_name))
    return to_julian_day(midnight)


def local_noon_jd(day: date, tz_name: str) -> float:
    noon = datetime.combine(day, time(12, 0), tzinfo=ZoneInfo(tz_name))
    return to_julian_day(noon)


def iso(moment: datetime) -> str:
    """Stable ISO-8601 output with a numeric offset and second precision."""
    return moment.isoformat(timespec="seconds")
