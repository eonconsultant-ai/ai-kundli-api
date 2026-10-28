from datetime import UTC, date, datetime, time

import pytest
import swisseph as swe

from app.services.astro.chart import build_kundli
from app.services.astro.constants import DASHA_YEARS
from app.services.astro.dasha import vimshottari
from app.services.astro.ephemeris import sidereal_positions
from app.services.astro.panchang import daily_panchang
from app.services.astro.time import resolve_local_moment, to_julian_day
from app.services.astro.varga import varga_sign

J2000 = 2451545.0


def test_lahiri_ayanamsa_at_j2000():
    swe.set_sid_mode(swe.SIDM_LAHIRI, 0, 0)
    assert swe.get_ayanamsa_ut(J2000) == pytest.approx(23.85709, abs=0.0001)


def test_sidereal_sun_at_j2000():
    positions = sidereal_positions(J2000, 28.6139, 77.2090)
    sun = positions.bodies["sun"]
    assert sun.longitude == pytest.approx(256.5157, abs=0.01)
    assert sun.sign == "Sagittarius"
    assert sun.nakshatra == "Purva Ashadha"
    assert positions.ascendant.as_dict()["house"] == 1


def test_whole_sign_houses_are_contiguous():
    positions = sidereal_positions(J2000, 28.6139, 77.2090)
    assert positions.houses[0]["house"] == 1
    assert positions.houses[0]["sign_index"] == positions.ascendant.sign_index
    assert {(house["sign_index"]) for house in positions.houses} == set(range(12))
    for body in positions.bodies.values():
        assert 1 <= body.house <= 12


@pytest.mark.parametrize(
    ("longitude", "divisions", "expected_sign"),
    [
        (0.0, 1, 0),
        (0.0, 3, 0),
        (10.0, 3, 4),
        (20.0, 3, 8),
        (30.0, 7, 7),
        (0.0, 9, 0),
        (30.0, 9, 9),
        (60.0, 9, 6),
        (90.0, 9, 3),
        (120.0, 9, 0),
        (30.0, 10, 9),
        (30.0, 12, 1),
    ],
)
def test_varga_sign_mapping(longitude, divisions, expected_sign):
    assert varga_sign(longitude, divisions) == expected_sign


def test_vimshottari_balance_at_exact_nakshatra_start():
    birth = datetime(1990, 1, 1, 6, 30, tzinfo=UTC)
    dasha = vimshottari(0.0, birth, "Asia/Kolkata")
    assert dasha["moon_nakshatra"] == "Ashwini"
    assert dasha["balance_at_birth"]["lord"] == "ketu"
    assert dasha["balance_at_birth"]["balance_years"] == pytest.approx(7.0)
    assert dasha["mahadashas"][0]["lord"] == "ketu"
    assert dasha["mahadashas"][0]["start"].startswith("1990-01-01")
    assert len(dasha["mahadashas"]) == 9
    assert sum(period["years"] for period in dasha["mahadashas"]) == pytest.approx(120.0)


def test_vimshottari_has_three_levels():
    birth = datetime(1990, 1, 1, 6, 30, tzinfo=UTC)
    dasha = vimshottari(
        45.0,
        birth,
        "Asia/Kolkata",
        include_pratyantar=True,
        at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    first = dasha["mahadashas"][0]
    assert len(first["children"]) == 9
    assert first["children"][0]["children"][0]["lord"] == first["lord"]
    assert {entry["level"] for entry in dasha["current"]["path"]} == {1, 2, 3}


def test_vimshottari_can_omit_pratyantar():
    birth = datetime(1990, 1, 1, 6, 30, tzinfo=UTC)
    dasha = vimshottari(45.0, birth, "Asia/Kolkata", include_pratyantar=False)
    assert dasha["mahadashas"][0]["children"][0]["children"] == []


def test_dasha_lords_sum_to_120():
    assert sum(DASHA_YEARS.values()) == 120


def test_panchang_structure_and_kaal_windows():
    panchang = daily_panchang(date(2024, 1, 1), 28.6139, 77.2090, "Asia/Kolkata")
    assert panchang["sunrise"] < panchang["sunset"]
    # Cross-checked against Drik Panchang for New Delhi on 2024-01-01.
    assert panchang["sunrise"].startswith("2024-01-01T07:13")
    assert panchang["sunset"].startswith("2024-01-01T17:35")
    assert panchang["tithi"]["name"] == "Panchami"
    assert panchang["tithi"]["paksha"] == "krishna"
    assert panchang["nakshatra"]["name"] == "Magha"
    assert panchang["yoga"]["name"] == "Ayushman"
    assert panchang["karana"]["name"] == "Taitila"
    assert 1 <= panchang["tithi"]["number"] <= 30
    assert 1 <= panchang["yoga"]["number"] <= 27
    assert 1 <= panchang["karana"]["number"] <= 60
    assert panchang["vara"]["name"] == "Monday"
    assert panchang["kaal"]["rahu"]["start"].startswith("2024-01-01T08:31")
    assert panchang["kaal"]["rahu"]["end"].startswith("2024-01-01T09:48")
    for name in ("rahu", "gulika", "yamaganda"):
        window = panchang["kaal"][name]
        assert panchang["sunrise"] <= window["start"] < window["end"] <= panchang["sunset"]


def test_full_kundli_for_known_birth_moment():
    chart = build_kundli(
        birth_date=date(1990, 1, 1),
        birth_time=time(12, 0),
        tz_name="Asia/Kolkata",
        latitude=28.6139,
        longitude=77.2090,
        name="Reference Chart",
        place_name="New Delhi",
    )
    assert len(chart["planets"]) == 9
    assert len(chart["houses"]) == 12
    assert {"D1", "D9", "D10"}.issubset(chart["vargas"])
    assert chart["subject"]["utc_offset_seconds"] == 19800
    assert chart["lagna"]["sign"] == "Pisces"
    assert chart["engine"]["ayanamsa"] == "lahiri"
    assert "tithi" in chart["panchang_at_birth"]
    assert chart["transits"]["planets"]
    assert chart["dashas"]["mahadashas"]


def test_historical_india_offset_is_not_hardcoded():
    # India observed +06:30 during World War II (1942-09 to 1945-10).
    moment = resolve_local_moment(date(1943, 1, 1), time(12, 0), "Asia/Kolkata")
    assert moment.local.utcoffset().total_seconds() == 23400
    assert to_julian_day(moment.utc) > 0
