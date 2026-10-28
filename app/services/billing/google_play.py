"""Google Play subscription verification.

Verification happens on the server so a modified client cannot grant itself
Plus. The service account needs the androidpublisher scope and access to the
Play Console app.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

from app.core.config import Settings

logger = logging.getLogger("jyotish.billing")

_SCOPE = "https://www.googleapis.com/auth/androidpublisher"
_ACTIVE_STATES = {
    "SUBSCRIPTION_STATE_ACTIVE",
    "SUBSCRIPTION_STATE_IN_GRACE_PERIOD",
    "SUBSCRIPTION_STATE_CANCELED",
}


class BillingNotConfigured(Exception):
    pass


class BillingVerificationError(Exception):
    pass


def _credentials(settings: Settings):
    raw = settings.google_play_service_account_json
    if not raw:
        raise BillingNotConfigured
    try:
        info = (
            json.loads(raw)
            if raw.strip().startswith("{")
            else json.loads(Path(raw).read_text(encoding="utf-8"))
        )
        return service_account.Credentials.from_service_account_info(info, scopes=[_SCOPE])
    except (OSError, ValueError, KeyError) as exc:
        raise BillingNotConfigured from exc


def verify_subscription(settings: Settings, *, product_id: str, purchase_token: str) -> dict:
    if product_id != settings.plus_product_id:
        raise BillingVerificationError("Unknown subscription product.")

    credentials = _credentials(settings)
    session = AuthorizedSession(credentials)
    package = quote(settings.google_play_package_name, safe="")
    token = quote(purchase_token, safe="")
    base = (
        "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"
        f"/{package}/purchases/subscriptionsv2/tokens/{token}"
    )

    response = session.get(base, timeout=20)
    if response.status_code != 200:
        logger.warning("Play subscription lookup returned %s: %s", response.status_code, response.text[:300])
        raise BillingVerificationError("Google Play could not verify this purchase.")

    data = response.json()
    state = data.get("subscriptionState")
    line_items = data.get("lineItems") or []
    matching = [item for item in line_items if item.get("productId") == product_id]
    if not matching:
        raise BillingVerificationError("This purchase is for a different product.")
    if state not in _ACTIVE_STATES:
        raise BillingVerificationError("This subscription is not active.")

    expiries = []
    for item in matching:
        raw_expiry = item.get("expiryTime")
        if not raw_expiry:
            continue
        expiry = datetime.fromisoformat(raw_expiry.replace("Z", "+00:00"))
        expiries.append(expiry)
    if not expiries:
        raise BillingVerificationError("This subscription has no expiry date.")

    expiry = max(expiries)
    if expiry <= datetime.now(UTC):
        raise BillingVerificationError("This subscription has expired.")

    if data.get("acknowledgementState") == "ACKNOWLEDGEMENT_STATE_PENDING":
        acknowledge = session.post(
            "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"
            f"/{package}/purchases/subscriptions/{token}:acknowledge",
            json={},
            timeout=20,
        )
        if acknowledge.status_code not in (200, 204, 409):
            logger.warning("Play acknowledge returned %s", acknowledge.status_code)

    return {
        "product_id": product_id,
        "state": state,
        "expires_at": expiry.isoformat(),
        "purchase_token": purchase_token,
    }
