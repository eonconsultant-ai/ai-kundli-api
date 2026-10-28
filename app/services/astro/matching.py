"""Ashtakoot Guna Milan, Mangal Dosha and Lagna compatibility."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any

from .chart import ENGINE_NAME, ENGINE_VERSION, mangal_dosha
from .constants import NAKSHATRAS
from .ephemeris import BodyPosition, ChartPositions, sidereal_positions
from .time import iso, resolve_local_moment, to_julian_day

ASHTAKOOT_MAX = 36

# Varna is ranked from Shudra (1) to Brahmin (4). A match scores one point when
# the groom's varna is equal to or higher than the bride's.
VARNA_BY_SIGN = (
    "kshatriya",  # Aries
    "vaishya",  # Taurus
    "shudra",  # Gemini
    "brahmin",  # Cancer
    "kshatriya",  # Leo
    "vaishya",  # Virgo
    "shudra",  # Libra
    "brahmin",  # Scorpio
    "kshatriya",  # Sagittarius
    "vaishya",  # Capricorn
    "shudra",  # Aquarius
    "brahmin",  # Pisces
)
VARNA_RANK = {"shudra": 1, "vaishya": 2, "kshatriya": 3, "brahmin": 4}

VASHYA_GROUPS = ("chatushpada", "manav", "jalachara", "vanachara", "keeta")

# Bride (row) against groom (column); classical two-point table.
VASHYA_SCORES = (
    (2, 1, 1, 1.5, 1),
    (1, 2, 1.5, 0, 1),
    (1, 1.5, 2, 1, 1),
    (0, 0, 0, 2, 0),
    (1, 1, 1, 0, 2),
)

YONI_ANIMALS = (
    "horse",
    "elephant",
    "sheep",
    "serpent",
    "dog",
    "cat",
    "rat",
    "cow",
    "buffalo",
    "tiger",
    "deer",
    "monkey",
    "mongoose",
    "lion",
)

# Bride (row) against groom (column); values are the classical 0-4 yoni points.
YONI_SCORES = (
    (4, 2, 2, 3, 2, 2, 2, 1, 0, 1, 3, 3, 2, 1),
    (2, 4, 3, 3, 2, 2, 2, 2, 3, 1, 2, 3, 2, 0),
    (2, 3, 4, 2, 1, 2, 1, 3, 3, 1, 2, 0, 3, 1),
    (3, 3, 2, 4, 2, 1, 1, 1, 1, 2, 2, 2, 0, 2),
    (2, 2, 1, 2, 4, 2, 1, 2, 2, 1, 0, 2, 1, 1),
    (2, 2, 2, 1, 2, 4, 0, 2, 2, 1, 3, 3, 2, 1),
    (2, 2, 1, 1, 1, 0, 4, 2, 2, 2, 2, 2, 1, 2),
    (1, 2, 3, 1, 2, 2, 2, 4, 3, 0, 3, 2, 2, 1),
    (0, 3, 3, 1, 2, 2, 2, 3, 4, 1, 2, 2, 2, 1),
    (1, 1, 1, 2, 1, 1, 2, 0, 1, 4, 1, 1, 2, 1),
    (3, 2, 2, 2, 0, 3, 2, 3, 2, 1, 4, 2, 2, 1),
    (3, 3, 0, 2, 2, 3, 2, 2, 2, 1, 2, 4, 3, 2),
    (2, 2, 3, 0, 1, 2, 1, 2, 2, 2, 2, 3, 4, 2),
    (1, 0, 1, 2, 1, 1, 2, 1, 2, 1, 1, 2, 2, 4),
)

GANA_ORDER = ("deva", "manushya", "rakshasa")
GANA_SCORES = (
    (6, 6, 0),
    (5, 6, 0),
    (1, 0, 6),
)

SIGN_LORDS = (
    "mars",
    "venus",
    "mercury",
    "moon",
    "sun",
    "mercury",
    "venus",
    "mars",
    "jupiter",
    "saturn",
    "saturn",
    "jupiter",
)

PLANET_FRIENDS = {
    "sun": {"friends": ("moon", "mars", "jupiter"), "enemies": ("venus", "saturn")},
    "moon": {"friends": ("sun", "mercury"), "enemies": ()},
    "mars": {"friends": ("sun", "moon", "jupiter"), "enemies": ("mercury",)},
    "mercury": {"friends": ("sun", "venus"), "enemies": ("moon",)},
    "jupiter": {"friends": ("sun", "moon", "mars"), "enemies": ("mercury", "venus")},
    "venus": {"friends": ("mercury", "saturn"), "enemies": ("sun", "moon")},
    "saturn": {"friends": ("mercury", "venus"), "enemies": ("sun", "moon", "mars")},
}

# Natural friendship, mutual friendship and enmity set the Graha Maitri score.
GRAHA_MAITRI_SCORES = {
    ("friend", "friend"): 5,
    ("friend", "neutral"): 4,
    ("neutral", "friend"): 4,
    ("neutral", "neutral"): 3,
    ("friend", "enemy"): 2,
    ("enemy", "friend"): 2,
    ("neutral", "enemy"): 1,
    ("enemy", "neutral"): 1,
    ("enemy", "enemy"): 0,
}


def _friendship(source: str, target: str) -> str:
    meta = PLANET_FRIENDS.get(source)
    if meta is None:
        return "neutral"
    if target in meta["friends"]:
        return "friend"
    if target in meta["enemies"]:
        return "enemy"
    return "neutral"


def _combined_relationship(first: str, second: str) -> str:
    relationships = {first, second}
    if relationships == {"friend"}:
        return "friends"
    if relationships == {"enemy"}:
        return "enemies"
    if "friend" in relationships and "enemy" in relationships:
        return "mixed"
    return "neutral"


def _vashya_group(body: BodyPosition) -> str:
    sign = body.sign_index
    if sign == 8:  # Sagittarius: first half human, second half quadruped.
        return "chatushpada" if body.degree_in_sign >= 15 else "manav"
    if sign == 9:  # Capricorn: first half quadruped, second half aquatic.
        return "jalachara" if body.degree_in_sign >= 15 else "chatushpada"
    if sign in (0, 1):
        return "chatushpada"
    if sign in (2, 5, 6, 10):
        return "manav"
    if sign in (3, 11):
        return "jalachara"
    if sign == 4:
        return "vanachara"
    return "keeta"


def _tara_points(bride_index: int, groom_index: int) -> tuple[float, int]:
    count = (groom_index - bride_index) % 27 + 1
    tara = count % 9 or 9
    return (0.0 if tara in (3, 5, 7) else 1.5, tara)


def _axis(first: int, second: int) -> str:
    low, high = sorted((first, second))
    return f"{low}/{high}"


def _nakshatra_meta(body: BodyPosition) -> dict[str, Any]:
    return NAKSHATRAS[body.nakshatra_index]


def _ashtakoot(bride: ChartPositions, groom: ChartPositions) -> dict[str, Any]:
    bride_moon = bride.bodies["moon"]
    groom_moon = groom.bodies["moon"]
    bride_nak = _nakshatra_meta(bride_moon)
    groom_nak = _nakshatra_meta(groom_moon)

    bride_varna = VARNA_BY_SIGN[bride_moon.sign_index]
    groom_varna = VARNA_BY_SIGN[groom_moon.sign_index]
    varna_score = 1 if VARNA_RANK[groom_varna] >= VARNA_RANK[bride_varna] else 0

    bride_vashya = _vashya_group(bride_moon)
    groom_vashya = _vashya_group(groom_moon)
    vashya_score = VASHYA_SCORES[VASHYA_GROUPS.index(bride_vashya)][
        VASHYA_GROUPS.index(groom_vashya)
    ]

    bride_tara, bride_tara_number = _tara_points(
        bride_moon.nakshatra_index, groom_moon.nakshatra_index
    )
    groom_tara, groom_tara_number = _tara_points(
        groom_moon.nakshatra_index, bride_moon.nakshatra_index
    )
    tara_score = bride_tara + groom_tara

    bride_yoni = str(bride_nak["yoni"])
    groom_yoni = str(groom_nak["yoni"])
    yoni_score = YONI_SCORES[YONI_ANIMALS.index(bride_yoni)][YONI_ANIMALS.index(groom_yoni)]

    bride_lord = SIGN_LORDS[bride_moon.sign_index]
    groom_lord = SIGN_LORDS[groom_moon.sign_index]
    bride_to_groom = _friendship(bride_lord, groom_lord)
    groom_to_bride = _friendship(groom_lord, bride_lord)
    graha_score = GRAHA_MAITRI_SCORES[(bride_to_groom, groom_to_bride)]

    bride_gana = str(bride_nak["gana"])
    groom_gana = str(groom_nak["gana"])
    gana_score = GANA_SCORES[GANA_ORDER.index(bride_gana)][GANA_ORDER.index(groom_gana)]

    groom_house = (groom_moon.sign_index - bride_moon.sign_index) % 12 + 1
    bhakoot_axis = _axis(groom_house, (bride_moon.sign_index - groom_moon.sign_index) % 12 + 1)
    bhakoot_score = 7 if bhakoot_axis not in ("2/12", "5/9", "6/8") else 0

    bride_nadi = str(bride_nak["nadi"])
    groom_nadi = str(groom_nak["nadi"])
    nadi_score = 8 if bride_nadi != groom_nadi else 0

    items = [
        {
            "key": "varna",
            "name": "Varna",
            "score": varna_score,
            "max": 1,
            "detail": f"Bride {bride_varna} · Groom {groom_varna}",
        },
        {
            "key": "vashya",
            "name": "Vashya",
            "score": vashya_score,
            "max": 2,
            "detail": f"Bride {bride_vashya} · Groom {groom_vashya}",
        },
        {
            "key": "tara",
            "name": "Tara",
            "score": tara_score,
            "max": 3,
            "detail": (
                f"Bride to groom tara {bride_tara_number} · "
                f"groom to bride tara {groom_tara_number}"
            ),
        },
        {
            "key": "yoni",
            "name": "Yoni",
            "score": yoni_score,
            "max": 4,
            "detail": f"Bride {bride_yoni} · Groom {groom_yoni}",
        },
        {
            "key": "graha_maitri",
            "name": "Graha Maitri",
            "score": graha_score,
            "max": 5,
            "detail": (
                f"{bride_lord.title()} is {bride_to_groom} to "
                f"{groom_lord.title()}; reverse is {groom_to_bride}"
            ),
        },
        {
            "key": "gana",
            "name": "Gana",
            "score": gana_score,
            "max": 6,
            "detail": f"Bride {bride_gana} · Groom {groom_gana}",
        },
        {
            "key": "bhakoot",
            "name": "Bhakoot",
            "score": bhakoot_score,
            "max": 7,
            "detail": (
                f"{bride_moon.sign} Moon to {groom_moon.sign} Moon · "
                f"{bhakoot_axis} axis"
            ),
        },
        {
            "key": "nadi",
            "name": "Nadi",
            "score": nadi_score,
            "max": 8,
            "detail": f"Bride {bride_nadi} · Groom {groom_nadi}",
        },
    ]

    total = round(sum(float(item["score"]) for item in items), 2)
    if total >= 30:
        verdict = "excellent"
    elif total >= 24:
        verdict = "very_good"
    elif total >= 18:
        verdict = "average"
    else:
        verdict = "needs_care"

    return {
        "total": total,
        "max": ASHTAKOOT_MAX,
        "percent": round(total / ASHTAKOOT_MAX * 100, 1),
        "verdict": verdict,
        "items": items,
        "doshas": [
            item["key"]
            for item in items
            if item["key"] in ("gana", "bhakoot", "nadi") and item["score"] == 0
        ],
    }


def _lagna_match(bride: ChartPositions, groom: ChartPositions) -> dict[str, Any]:
    bride_lagna = bride.ascendant.sign_index
    groom_lagna = groom.ascendant.sign_index
    bride_lord = SIGN_LORDS[bride_lagna]
    groom_lord = SIGN_LORDS[groom_lagna]

    bride_to_groom = _friendship(bride_lord, groom_lord)
    groom_to_bride = _friendship(groom_lord, bride_lord)
    relationship = _combined_relationship(bride_to_groom, groom_to_bride)

    groom_house = (groom_lagna - bride_lagna) % 12 + 1
    reverse_house = (bride_lagna - groom_lagna) % 12 + 1
    axis = _axis(groom_house, reverse_house)
    base = {
        "1/1": 7,
        "2/12": 5,
        "3/11": 8,
        "4/10": 6,
        "5/9": 8,
        "6/8": 3,
        "7/7": 9,
    }[axis]
    if relationship == "friends":
        base += 1
    elif relationship == "enemies":
        base -= 1
    score = max(1, min(10, base))

    notes = {
        "1/1": "Same Lagna: similar temperament and habits.",
        "2/12": "2/12 axis: practical differences in resources and outlook.",
        "3/11": "3/11 axis: supportive and mutually encouraging.",
        "4/10": "4/10 axis: home and career pull in different directions.",
        "5/9": "5/9 axis: dharma and purpose align well.",
        "6/8": "6/8 axis: needs care; health and service themes recur.",
        "7/7": "1/7 axis: a natural partnership axis.",
    }

    return {
        "bride_lagna": bride.ascendant.sign,
        "groom_lagna": groom.ascendant.sign,
        "bride_lord": bride_lord,
        "groom_lord": groom_lord,
        "house_from_bride": groom_house,
        "axis": axis,
        "friendship": relationship,
        "score": score,
        "max": 10,
        "summary": notes[axis],
    }


def _person_summary(positions: ChartPositions, name: str | None) -> dict[str, Any]:
    moon = positions.bodies["moon"]
    dosha = mangal_dosha(positions)
    return {
        "name": name,
        "moon_sign": moon.sign,
        "moon_sign_sanskrit": moon.sign_sanskrit,
        "moon_nakshatra": moon.nakshatra,
        "moon_pada": moon.pada,
        "lagna_sign": positions.ascendant.sign,
        "lagna_sanskrit": positions.ascendant.sign_sanskrit,
        "is_manglik": dosha["is_manglik"],
        "manglik_from": dosha["active_from"],
    }


def _mangal_compatibility(
    bride: ChartPositions,
    groom: ChartPositions,
) -> dict[str, Any]:
    bride_dosha = mangal_dosha(bride)
    groom_dosha = mangal_dosha(groom)
    bride_manglik = bool(bride_dosha["is_manglik"])
    groom_manglik = bool(groom_dosha["is_manglik"])

    if bride_manglik and groom_manglik:
        status = "both_manglik"
        compatible = True
        note = "Both charts carry Mangal Dosha, which is traditionally treated as balanced."
    elif not bride_manglik and not groom_manglik:
        status = "both_non_manglik"
        compatible = True
        note = "Neither chart carries Mangal Dosha."
    elif bride_manglik:
        status = "bride_manglik"
        compatible = False
        note = "The bride's chart carries Mangal Dosha; cancellation rules should be reviewed."
    else:
        status = "groom_manglik"
        compatible = False
        note = "The groom's chart carries Mangal Dosha; cancellation rules should be reviewed."

    return {
        "bride_is_manglik": bride_manglik,
        "groom_is_manglik": groom_manglik,
        "bride_from": bride_dosha["active_from"],
        "groom_from": groom_dosha["active_from"],
        "compatible": compatible,
        "status": status,
        "note": note,
    }


def compute_matching(
    *,
    bride_date: date,
    bride_time: time,
    bride_tz: str,
    bride_latitude: float,
    bride_longitude: float,
    groom_date: date,
    groom_time: time,
    groom_tz: str,
    groom_latitude: float,
    groom_longitude: float,
    bride_name: str | None = None,
    groom_name: str | None = None,
    ayanamsa: str = "lahiri",
    node_mode: str = "true",
    systems: list[str] | None = None,
) -> dict[str, Any]:
    selected = systems or ["ashtakoot", "mangal_dosha", "lagna"]

    resolved_bride = resolve_local_moment(bride_date, bride_time, bride_tz)
    resolved_groom = resolve_local_moment(groom_date, groom_time, groom_tz)

    bride_positions = sidereal_positions(
        to_julian_day(resolved_bride.utc),
        bride_latitude,
        bride_longitude,
        ayanamsa=ayanamsa,
        node_mode=node_mode,
    )
    groom_positions = sidereal_positions(
        to_julian_day(resolved_groom.utc),
        groom_latitude,
        groom_longitude,
        ayanamsa=ayanamsa,
        node_mode=node_mode,
    )

    return {
        "bride": _person_summary(bride_positions, bride_name),
        "groom": _person_summary(groom_positions, groom_name),
        "ashtakoot": (
            _ashtakoot(bride_positions, groom_positions)
            if "ashtakoot" in selected
            else None
        ),
        "mangal_dosha": (
            _mangal_compatibility(bride_positions, groom_positions)
            if "mangal_dosha" in selected
            else None
        ),
        "lagna_match": (
            _lagna_match(bride_positions, groom_positions)
            if "lagna" in selected
            else None
        ),
        "engine": {
            "name": ENGINE_NAME,
            "version": ENGINE_VERSION,
            "ephemeris": bride_positions.ephemeris,
            "ayanamsa": ayanamsa,
            "node_mode": node_mode,
            "computed_at": iso(datetime.now(UTC)),
            "warnings": list(resolved_bride.warnings) + list(resolved_groom.warnings),
        },
        "disclaimer": (
            "Kundli Milan is a traditional compatibility guide. It is not a "
            "decision-making authority, and lineage-specific cancellation rules "
            "are not applied."
        ),
    }
