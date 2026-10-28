"""Anonymous usage counters for the app owner's dashboard.

Only event names and a small label are accepted, keyed by the random install ID.
Birth details, questions and replies never reach this endpoint, so the counters
stay aggregated numbers rather than a behavioural profile.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request

from app.api.v1.identity import install_id as resolve_install_id
from app.core.config import get_settings
from app.schemas.events import EventBatch
from app.services.ai import store

router = APIRouter(tags=["events"])

SCREEN_LABELS = frozenset(
    {
        "panchang",
        "kundli",
        "kundli_report",
        "ai_reading",
        "ai_chat",
        "ai_voice",
        "life_chart",
        "lal_kitab",
        "matching",
        "matching_result",
        "horoscope",
        "profile",
        "saved_charts",
        "place_picker",
    }
)

AD_LABELS = frozenset(
    {
        "kundli_dasha_detail",
        "ai_kundli_reading",
        "ai_kundli_chat",
        "ai_kundli_voice",
        "kundli_result",
        "matching_result",
    }
)

EVENT_NAMES = frozenset(
    {
        "app_open",
        "screen_view",
        "paywall_viewed",
        "restore_tapped",
        "purchase_started",
        "purchase_completed",
        "rewarded_shown",
        "rewarded_earned",
        "rewarded_dismissed",
        "rewarded_unavailable",
        "interstitial_shown",
    }
)

LABELS = SCREEN_LABELS | AD_LABELS


@router.post("/events", status_code=202, summary="Record anonymous usage counters")
def record_events(
    payload: EventBatch,
    request: Request,
    x_install_id: Annotated[str | None, Header(alias="X-Install-Id")] = None,
) -> dict:
    unknown = sorted({event.name for event in payload.events} - EVENT_NAMES)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown event name: {', '.join(unknown)}")
    unknown_labels = sorted({event.label for event in payload.events if event.label} - LABELS)
    if unknown_labels:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown event label: {', '.join(unknown_labels)}",
        )

    settings = get_settings()
    install_id = resolve_install_id(x_install_id, request)
    accepted = store.get(settings).record_events(
        install_id,
        [(event.name, event.label) for event in payload.events],
    )
    return {"accepted": accepted}


@router.get("/events/summary", summary="Owner-only usage dashboard")
def events_summary(
    days: Annotated[int, Query(ge=1, le=90)] = 14,
    x_analytics_token: Annotated[str | None, Header(alias="X-Analytics-Token")] = None,
) -> dict:
    settings = get_settings()
    expected = (settings.analytics_token or "").strip()
    # No token configured means no dashboard: hiding the route is safer than
    # serving it to anyone who guesses the path.
    if not expected:
        raise HTTPException(status_code=404, detail="Not found.")
    if not x_analytics_token or not secrets.compare_digest(x_analytics_token, expected):
        raise HTTPException(status_code=401, detail="Invalid analytics token.")
    return store.get(settings).activity(days)
