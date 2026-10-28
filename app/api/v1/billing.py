from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request

from app.api.v1.identity import install_id, valid_install_id
from app.core.config import Settings, get_settings
from app.schemas.billing import BillingVerifyRequest
from app.services.ai import store
from app.services.billing.google_play import (
    BillingNotConfigured,
    BillingVerificationError,
    verify_subscription,
)

logger = logging.getLogger("jyotish.billing")

router = APIRouter(tags=["billing"])

_refresh_lock = threading.Lock()
_last_refresh: dict[str, datetime] = {}


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _refresh_due(identity: str, updated_at: str | None, cutoff: datetime) -> bool:
    checked = _parse(updated_at)
    if checked is not None and checked > cutoff:
        return False
    with _refresh_lock:
        attempted = _last_refresh.get(identity)
        if attempted is not None and attempted > cutoff:
            return False
        if len(_last_refresh) > 2000:
            for key in [key for key, when in _last_refresh.items() if when <= cutoff]:
                _last_refresh.pop(key, None)
        _last_refresh[identity] = datetime.now(UTC)
    return True


def _refresh_plus(settings: Settings, identity: str) -> None:
    """Re-check Google Play so subscription renewals extend the stored expiry."""
    usage = store.get(settings)
    record = usage.entitlement_record(identity)
    if not record:
        return
    token = record["purchase_token"]
    if record["source"] != "google_play" or not token:
        return
    if not settings.google_play_service_account_json:
        return
    cutoff = datetime.now(UTC) - timedelta(hours=settings.plus_refresh_hours)
    if not _refresh_due(identity, record["updated_at"], cutoff):
        return

    try:
        verified = verify_subscription(
            settings,
            product_id=settings.plus_product_id,
            purchase_token=token,
        )
    except (BillingNotConfigured, BillingVerificationError) as exc:
        # Keep the stored row: a Play outage must not revoke an active subscription.
        logger.warning("Plus refresh failed for %s: %s", identity, exc)
        return

    usage.grant_plus(
        identity,
        expires_at=verified["expires_at"],
        source="google_play",
        purchase_token=verified["purchase_token"],
    )


@router.get("/billing/entitlement", summary="Current AI Kundli Plus entitlement")
def entitlement(
    request: Request,
    x_install_id: Annotated[str | None, Header(alias="X-Install-Id")] = None,
) -> dict:
    settings = get_settings()
    identity = install_id(x_install_id, request)
    _refresh_plus(settings, identity)
    row = store.get(settings).entitlement(identity)
    return {
        "plus": row is not None,
        "plan": row["plan"] if row else None,
        "expires_at": row["expires_at"] if row else None,
        "product_id": settings.plus_product_id,
        "billing_configured": bool(settings.google_play_service_account_json),
    }


@router.post("/billing/google/verify", summary="Verify a Google Play subscription purchase")
def verify(
    payload: BillingVerifyRequest,
    request: Request,
    x_install_id: Annotated[str | None, Header(alias="X-Install-Id")] = None,
) -> dict:
    settings = get_settings()
    identity = valid_install_id(x_install_id)
    if identity is None:
        raise HTTPException(status_code=400, detail="A valid install ID is required.")
    if payload.product_id != settings.plus_product_id:
        raise HTTPException(status_code=400, detail="Unknown subscription product.")

    try:
        verified = verify_subscription(
            settings,
            product_id=payload.product_id,
            purchase_token=payload.purchase_token,
        )
    except BillingNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Billing is not configured on this server.") from exc
    except BillingVerificationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    store.get(settings).grant_plus(
        identity,
        expires_at=verified["expires_at"],
        source="google_play",
        purchase_token=verified["purchase_token"],
    )
    return {
        "plus": True,
        "plan": "plus",
        "expires_at": verified["expires_at"],
        "state": verified["state"],
        "product_id": verified["product_id"],
    }
