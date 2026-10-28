from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.schemas.astro import EngineMeta, KundliRequest, MatchingRequest
from app.services.astro.chart import ENGINE_NAME, ENGINE_VERSION, build_kundli
from app.services.astro.constants import VARGA_NAMES
from app.services.astro.matching import compute_matching
from app.services.astro.panchang import daily_panchang

router = APIRouter(tags=["astrology"])


@router.post("/kundli/compute", summary="Compute a complete birth chart")
def compute_kundli(payload: KundliRequest) -> dict:
    return build_kundli(
        birth_date=payload.birth_date,
        birth_time=payload.birth_time,
        tz_name=payload.timezone,
        latitude=payload.latitude,
        longitude=payload.longitude,
        name=payload.name,
        place_name=payload.place_name,
        altitude_m=payload.altitude_m,
        ayanamsa=payload.ayanamsa,
        node_mode=payload.node_mode,
        include_pratyantar=payload.include_pratyantar,
        transit_at=payload.transit_at,
    )


@router.post("/matching/compute", summary="Ashtakoot Guna Milan and marriage compatibility")
def matching(payload: MatchingRequest) -> dict:
    return compute_matching(
        bride_date=payload.bride.birth_date,
        bride_time=payload.bride.birth_time,
        bride_tz=payload.bride.timezone,
        bride_latitude=payload.bride.latitude,
        bride_longitude=payload.bride.longitude,
        bride_name=payload.bride.name,
        groom_date=payload.groom.birth_date,
        groom_time=payload.groom.birth_time,
        groom_tz=payload.groom.timezone,
        groom_latitude=payload.groom.latitude,
        groom_longitude=payload.groom.longitude,
        groom_name=payload.groom.name,
        ayanamsa=payload.ayanamsa,
        node_mode=payload.node_mode,
        systems=list(dict.fromkeys(payload.systems)),
    )


@router.get("/panchang", summary="Daily Panchang for a place and date")
def panchang(
    on_date: Annotated[date, Query(alias="date")],
    latitude: Annotated[float, Query(ge=-90, le=90)],
    longitude: Annotated[float, Query(ge=-180, le=180)],
    timezone: Annotated[str, Query(min_length=1, max_length=64)],
    altitude_m: Annotated[float, Query(ge=-500, le=9000)] = 0,
    ayanamsa: Annotated[str, Query(pattern="^(lahiri|raman|krishnamurti|true_citra)$")] = "lahiri",
    node_mode: Annotated[str, Query(pattern="^(true|mean)$")] = "true",
) -> dict:
    return daily_panchang(
        on_date,
        latitude,
        longitude,
        timezone,
        altitude_m=altitude_m,
        ayanamsa=ayanamsa,
        node_mode=node_mode,
    )


@router.get("/engine/meta", response_model=EngineMeta)
def engine_meta() -> EngineMeta:
    from app.core.config import get_settings

    ephe_path = get_settings().ephe_path
    has_files = ephe_path.exists() and any(ephe_path.glob("*.se1"))
    return EngineMeta(
        name=ENGINE_NAME,
        version=ENGINE_VERSION,
        ayanamsas=["lahiri", "raman", "krishnamurti", "true_citra"],
        vargas=VARGA_NAMES,
        node_modes=["true", "mean"],
        ephemeris_files_present=has_files,
    )
