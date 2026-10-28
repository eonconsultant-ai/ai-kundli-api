"""Vimshottari dasha to the pratyantardasha level."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .constants import (
    DASHA_SEQUENCE,
    DASHA_TOTAL_YEARS,
    DASHA_YEAR_DAYS,
    DASHA_YEARS,
    NAKSHATRA_SPAN,
    NAKSHATRAS,
)
from .time import iso


@dataclass(frozen=True)
class DashaPeriod:
    lord: str
    start: datetime
    end: datetime
    years: float
    level: int
    children: tuple[DashaPeriod, ...] = ()


def _lord_index(lord: str) -> int:
    return DASHA_SEQUENCE.index(lord)


def _children(
    parent_lord: str,
    start: datetime,
    total_days: float,
    *,
    level: int,
    max_level: int,
) -> tuple[DashaPeriod, ...]:
    if level > max_level:
        return ()

    parent_index = _lord_index(parent_lord)
    periods: list[DashaPeriod] = []
    cursor = start
    for offset in range(9):
        lord = DASHA_SEQUENCE[(parent_index + offset) % 9]
        child_days = total_days * DASHA_YEARS[lord] / DASHA_TOTAL_YEARS
        end = cursor + timedelta(days=child_days)
        periods.append(
            DashaPeriod(
                lord=lord,
                start=cursor,
                end=end,
                years=child_days / DASHA_YEAR_DAYS,
                level=level,
                children=_children(
                    lord,
                    cursor,
                    child_days,
                    level=level + 1,
                    max_level=max_level,
                ),
            )
        )
        cursor = end
    return tuple(periods)


def _serialize(period: DashaPeriod, tz: ZoneInfo) -> dict:
    return {
        "lord": period.lord,
        "start": iso(period.start.astimezone(tz)),
        "end": iso(period.end.astimezone(tz)),
        "years": round(period.years, 6),
        "children": [_serialize(child, tz) for child in period.children],
    }


def _find_path(periods: tuple[DashaPeriod, ...], at: datetime) -> list[DashaPeriod]:
    for period in periods:
        if period.start <= at < period.end:
            return [period, *_find_path(period.children, at)]
    return []


def vimshottari(
    moon_longitude: float,
    birth_utc: datetime,
    tz_name: str,
    *,
    include_pratyantar: bool = True,
    at: datetime | None = None,
) -> dict:
    """Build the full Vimshottari tree for a native's Moon longitude.

    The first mahadasha may begin before birth; its balance is what remains at
    birth. Antardasha and pratyantardasha sequences start from their parent lord.
    """
    moon_longitude %= 360
    nak_index = int(moon_longitude / NAKSHATRA_SPAN) % 27
    nak = NAKSHATRAS[nak_index]
    start_lord = str(nak["lord"])
    fraction_elapsed = (moon_longitude % NAKSHATRA_SPAN) / NAKSHATRA_SPAN

    start_index = _lord_index(start_lord)
    first_days = DASHA_YEARS[start_lord] * DASHA_YEAR_DAYS
    first_start = birth_utc - timedelta(days=first_days * fraction_elapsed)

    max_children = 3 if include_pratyantar else 2
    mahadashas: list[DashaPeriod] = []
    cursor = first_start
    for offset in range(9):
        lord = DASHA_SEQUENCE[(start_index + offset) % 9]
        total_days = DASHA_YEARS[lord] * DASHA_YEAR_DAYS
        end = cursor + timedelta(days=total_days)
        mahadashas.append(
            DashaPeriod(
                lord=lord,
                start=cursor,
                end=end,
                years=DASHA_YEARS[lord],
                level=1,
                children=_children(
                    lord,
                    cursor,
                    total_days,
                    level=2,
                    max_level=max_children,
                ),
            )
        )
        cursor = end

    balance_years = DASHA_YEARS[start_lord] * (1 - fraction_elapsed)
    balance_end = mahadashas[0].end

    current = at or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current_utc = current.astimezone(UTC)
    path = _find_path(tuple(mahadashas), current_utc)
    tz = ZoneInfo(tz_name)

    return {
        "system": "vimshottari",
        "year_basis_days": DASHA_YEAR_DAYS,
        "moon_nakshatra": str(nak["name"]),
        "moon_nakshatra_index": nak_index,
        "nakshatra_lord": start_lord,
        "balance_at_birth": {
            "lord": start_lord,
            "total_years": DASHA_YEARS[start_lord],
            "elapsed_years": round(DASHA_YEARS[start_lord] * fraction_elapsed, 6),
            "balance_years": round(balance_years, 6),
            "balance_ends_at": iso(balance_end.astimezone(tz)),
        },
        "current": {
            "as_of": iso(current_utc.astimezone(tz)),
            "path": [
                {
                    "level": period.level,
                    "lord": period.lord,
                    "start": iso(period.start.astimezone(tz)),
                    "end": iso(period.end.astimezone(tz)),
                }
                for period in path
            ],
        },
        "mahadashas": [_serialize(period, tz) for period in mahadashas],
    }
