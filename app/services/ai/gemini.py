"""Shared Gemini request helper with model and API-key fallback.

Google retires models regularly and free-tier quotas are per project and model.
Trying every model/key pair keeps the app working across a shutdown, a revoked
key or a rate limit. Keys only add capacity when they belong to separate Google
Cloud projects; several keys in one project share the same quota.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from app.core.config import Settings

logger = logging.getLogger("jyotish.ai.gemini")

_COOLDOWN_SECONDS = 60
_cooldown_lock = threading.Lock()
_cooling_until: dict[tuple[str, str], float] = {}


def _post(
    settings: Settings,
    key: str,
    model: str,
    body: dict[str, Any],
) -> httpx.Response | None:
    url = f"{settings.gemini_base_url}/models/{model}:generateContent"
    try:
        with httpx.Client(timeout=settings.ai_timeout_seconds) as client:
            return client.post(
                url,
                headers={"x-goog-api-key": key},
                json=body,
            )
    except Exception as exc:  # noqa: BLE001 - every AI failure must fall back
        logger.warning("Gemini %s request failed: %s", model, exc)
        return None


def _search_tool_rejected(response: httpx.Response | None) -> bool:
    if response is None or response.status_code not in (400, 403, 404):
        return False
    text = response.text.lower()
    return "tool" in text or "search" in text or "grounding" in text


def _is_cooling(key: str, model: str) -> bool:
    with _cooldown_lock:
        until = _cooling_until.get((key, model), 0.0)
        if until > time.monotonic():
            return True
        _cooling_until.pop((key, model), None)
        return False


def _cool_down(key: str, model: str) -> None:
    now = time.monotonic()
    with _cooldown_lock:
        if len(_cooling_until) > 500:
            for pair, until in list(_cooling_until.items()):
                if until <= now:
                    _cooling_until.pop(pair, None)
        _cooling_until[(key, model)] = now + _COOLDOWN_SECONDS


def generate_content(settings: Settings, body: dict[str, Any]) -> tuple[dict[str, Any], str] | None:
    keys = settings.gemini_keys
    if not keys:
        return None

    for model in settings.gemini_models:
        for key in keys:
            if _is_cooling(key, model):
                continue

            response = _post(settings, key, model, body)

            if response is not None and response.status_code == 200:
                return response.json(), model

            if response is not None and response.status_code == 429:
                if body.get("tools"):
                    # Search grounding carries its own quota and is exhausted on
                    # some free keys, so ask again without the tool rather than
                    # losing the reply.
                    plain_body = {item: value for item, value in body.items() if item != "tools"}
                    retry = _post(settings, key, model, plain_body)
                    if retry is not None and retry.status_code == 200:
                        logger.info("Gemini %s answered without search grounding", model)
                        return retry.json(), model
                # Stay off this key/model pair for a minute instead of piling
                # more rate-limited calls onto it.
                _cool_down(key, model)
                logger.warning("Gemini %s rate-limited key ...%s", model, key[-4:])
                continue

            # Search grounding is not available on every model or tier. Retry
            # the same pair without the tool instead of losing the reply.
            if body.get("tools") and _search_tool_rejected(response):
                logger.info("Gemini %s rejected search grounding; retrying without tools", model)
                plain_body = {item: value for item, value in body.items() if item != "tools"}
                response = _post(settings, key, model, plain_body)
                if response is not None and response.status_code == 200:
                    return response.json(), model

            if response is not None:
                logger.warning(
                    "Gemini %s returned %s: %s",
                    model,
                    response.status_code,
                    response.text[:300],
                )

    return None
