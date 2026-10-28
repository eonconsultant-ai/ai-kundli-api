"""Optional second text provider for chat.

Groq speaks the OpenAI chat-completions schema, so this is a plain HTTP call
with the same key pooling and 429 cooldown as Gemini. It is only reached after
every Gemini model/key pair has failed, and it has no search grounding: replies
come from the model alone.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from app.core.config import Settings

logger = logging.getLogger("jyotish.ai.groq")

_COOLDOWN_SECONDS = 60
_cooldown_lock = threading.Lock()
_cooling_until: dict[str, float] = {}


def _is_cooling(key: str) -> bool:
    with _cooldown_lock:
        until = _cooling_until.get(key, 0.0)
        if until > time.monotonic():
            return True
        _cooling_until.pop(key, None)
        return False


def _cool_down(key: str) -> None:
    now = time.monotonic()
    with _cooldown_lock:
        if len(_cooling_until) > 100:
            for parked, until in list(_cooling_until.items()):
                if until <= now:
                    _cooling_until.pop(parked, None)
        _cooling_until[key] = now + _COOLDOWN_SECONDS


def chat_completion(
    settings: Settings,
    *,
    system: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float = 0.7,
) -> tuple[str, str] | None:
    """Return (reply, model) or None when Groq is unconfigured or failing."""
    keys = settings.groq_keys
    if not keys:
        return None

    body: dict[str, Any] = {
        "model": settings.groq_model,
        "messages": [{"role": "system", "content": system}, *messages],
        "temperature": temperature,
        "top_p": 0.9,
        "max_tokens": max_tokens,
    }
    url = f"{settings.groq_base_url}/chat/completions"

    for key in keys:
        if _is_cooling(key):
            continue
        try:
            with httpx.Client(timeout=settings.groq_timeout_seconds) as client:
                response = client.post(
                    url,
                    headers={"authorization": f"Bearer {key}"},
                    json=body,
                )
        except Exception as exc:  # noqa: BLE001 - every AI failure must fall back
            logger.warning("Groq request failed: %s", exc)
            continue

        if response.status_code == 200:
            try:
                choice = (response.json().get("choices") or [{}])[0]
                text = ((choice.get("message") or {}).get("content") or "").strip()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Groq reply was unreadable: %s", exc)
                continue
            if text:
                return text, settings.groq_model
            logger.warning("Groq returned an empty reply")
            continue

        if response.status_code == 429:
            _cool_down(key)
            logger.warning("Groq rate-limited key ...%s", key[-4:])
            continue

        logger.warning("Groq returned %s: %s", response.status_code, response.text[:300])

    return None
