"""Voice "AI Panditji talk" over the Gemini Live API.

The app never holds the Gemini key. It asks for a short-lived session token, then
opens our WebSocket, and we proxy the bidirectional audio to Google. One session
token is one push-to-talk turn: the user asks one question and hears one answer.

Birth details stay on this server. The setup instruction only carries derived
chart facts plus the recent conversation, exactly like the text chat.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import websockets

from app.core.config import Settings
from app.services.ai import store
from app.services.ai.gemini import _cool_down, _is_cooling

logger = logging.getLogger("jyotish.ai.live")

LIVE_PRIVACY = (
    "Your microphone audio goes to the AI voice service through our server. "
    "Your name, birth date, birth time and birthplace are never sent."
)

LIVE_SYSTEM = """You are "AI Panditji" (AI Jyotish), a sixty-year-old Indian Vedic priest and Jyotish acharya.
You are speaking aloud inside a mobile app.
You have spent your life in puja, mantra and study. You are calm, warm and paternal, like an elder of the family.
The app computed the chart and gives you verified facts. Use only those facts.

Voice and manner:
- Sound like an old Indian priest talking, not a narrator or a call-centre agent: unhurried, gentle, grounded.
- Speak slowly and evenly, the way a grounded old guru speaks: steady breath, unhurried pace,
  a low warm tone. Let the voice rise and fall gently, soften on the comforting line, and
  pause briefly before the final step. Never rush, never sound excited, never recite in one flat monotone.
- This is speech, not writing: short natural sentences, no markdown, lists, headings, emoji or stage directions.
- No theatrical blessings, no drama. Address the user as "beta" at most once in an answer, only when it fits naturally.

Language:
- Hindi is your default. Speak Hindi in Devanagari unless the user's latest message was spoken in English.
- Write Hindi words in Devanagari script, never in Roman letters, because the user reads them on screen.
- Switch to English only when the user clearly speaks English in their latest message.
- If the user mixes Hindi and English, answer in the same easy mix.
- Keep every sentence simple enough to follow by ear.

Dharma:
- Speak as a dharma guide, not a fortune teller. Present every suggestion as dharma:
  duty, right conduct, patience, service and steady practice.
- Frame everything as tendency and reflection, not certainty. Use words like "may", "tends to", "consider".
- Never predict death, serious illness, accidents, divorce, infertility or financial ruin.
- Never diagnose or treat health conditions. Never give medical, legal or financial
  instructions; suggest a qualified professional for those.
- Remedies must be free or low-cost cultural practices (mantra japa, charity, routine,
  journalling, breath work, service). No gemstones, expensive rituals or fear.
- Never mention the user's name, birth date, birth time or birthplace; you do not receive them.
  Never ask for them or invent them.

Length: about 40 to 80 spoken words, roughly thirty seconds.
End with one small practical step or one gentle follow-up question.
"""

_VOICE_MIME = "audio/pcm;rate=16000"


@dataclass
class LiveSession:
    token: str
    install_id: str
    plus: bool
    facts: dict[str, Any]
    language: str
    history: list[dict[str, str]] = field(default_factory=list)
    consumed: bool = False
    model: str | None = None


def build_system(facts: dict[str, Any], language: str, history: list[dict[str, str]]) -> str:
    lines = [LIVE_SYSTEM]
    # "Hari OM" is a greeting, not a refrain: it belongs to the very first answer
    # of the conversation and nowhere else.
    if history:
        lines.append('This is a continuing conversation. Do not say "Hari OM" again.')
    else:
        lines.append(
            'This is the first answer of the conversation: open it with the greeting "Hari OM" '
            '(हरि ॐ when the answer is in Hindi), then go straight into the guidance.'
        )
    if language == "hi":
        lines.append("App language: Hindi. Start in Hindi.")
    else:
        lines.append(
            "App language: English. Hindi is still your default; answer in English only when the user speaks English."
        )
    if history:
        lines.append("Conversation so far:")
        for turn in history[-8:]:
            speaker = "User" if turn.get("role") == "user" else "Panditji"
            lines.append(f"{speaker}: {turn.get('content', '')}")
    lines.append(f"Verified chart facts: {json.dumps(facts, ensure_ascii=False)}")
    return "\n".join(lines)


def prune_expired(settings: Settings) -> list[str]:
    """Delete expired tokens and give back the turn each was holding."""
    usage = store.get(settings)
    install_ids = usage.take_expired_live_sessions(time.time())
    for install_id in install_ids:
        usage.refund_live_turn(install_id)
        usage.refund_global()
    return install_ids


def new_session(
    settings: Settings,
    *,
    install_id: str,
    plus: bool,
    facts: dict[str, Any],
    language: str,
    history: list[dict[str, str]],
) -> LiveSession:
    prune_expired(settings)
    usage = store.get(settings)
    session = LiveSession(
        token=secrets.token_urlsafe(32),
        install_id=install_id,
        plus=plus,
        facts=facts,
        language=language,
        history=history,
    )
    usage.save_live_session(
        token=session.token,
        install_id=install_id,
        plus=plus,
        facts=facts,
        language=language,
        history=history,
        expires_at=time.time() + settings.live_session_token_ttl_seconds,
    )
    return session


def take_session(settings: Settings, token: str) -> LiveSession | None:
    """Single-use: the token row is deleted as soon as a stream claims it."""
    if not token:
        return None
    record = store.get(settings).claim_live_session(token, time.time())
    if record is None:
        return None
    return LiveSession(
        token=token,
        install_id=record["install_id"],
        plus=record["plus"],
        facts=record["facts"],
        language=record["language"],
        history=record["history"],
    )


def refund_session(settings: Settings, session: LiveSession) -> None:
    if not session.consumed:
        session.consumed = True
        usage = store.get(settings)
        usage.refund_live_turn(session.install_id)
        usage.refund_global()


def mark_used(session: LiveSession, model: str) -> None:
    session.consumed = True
    session.model = model


def _live_url(settings: Settings) -> str:
    # gemini_base_url holds the REST version (/v1beta), while the Live socket
    # path spells its own version out. Keep only the origin to avoid
    # wss://host/v1beta/ws/...v1beta... (which the server answers with 404).
    origin = urlsplit(settings.gemini_base_url)
    scheme = "wss" if origin.scheme == "https" else "ws"
    return f"{scheme}://{origin.netloc}/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"


def _setup_message(settings: Settings, model: str, system: str) -> dict[str, Any]:
    return {
        "setup": {
            "model": f"models/{model}",
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    # The persona is Hindi-first and the same native voice carries
                    # English replies, so the greeting and the accent stay Indian.
                    "languageCode": "hi-IN",
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": settings.live_voice_name},
                    },
                },
            },
            # Push-to-talk: the app marks exactly when the user starts and stops,
            # so a turn map to one button press instead of an energy threshold.
            "realtimeInputConfig": {"automaticActivityDetection": {"disabled": True}},
            "inputAudioTranscription": {},
            "outputAudioTranscription": {},
        }
    }


def _json_frame(raw: str | bytes) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


async def connect_live(
    settings: Settings,
    system: str,
) -> tuple[Any, str] | tuple[None, None]:
    """Open a Live connection, falling back across models and keys."""
    keys = settings.gemini_keys
    if not keys:
        return None, None

    url = _live_url(settings)
    for model in settings.gemini_live_models:
        for key in keys:
            if _is_cooling(key, model):
                continue
            try:
                socket = await websockets.connect(
                    url,
                    additional_headers={"x-goog-api-key": key},
                    open_timeout=10,
                    close_timeout=5,
                    max_size=None,
                )
            except Exception as exc:  # noqa: BLE001 - try the next model/key
                logger.warning("Live %s connect failed: %s", model, exc)
                continue

            try:
                await socket.send(json.dumps(_setup_message(settings, model, system)))
                raw = await asyncio.wait_for(socket.recv(), timeout=12)
            except Exception as exc:  # noqa: BLE001 - setup can fail on quota or a retired model
                logger.warning("Live %s setup failed: %s", model, exc)
                await socket.close()
                continue

            data = _json_frame(raw)
            if data and "setupComplete" in data:
                return socket, model

            error = (data or {}).get("error") or {}
            code = error.get("code")
            logger.warning("Live %s rejected setup (code %s): %s", model, code, str(data)[:300])
            await socket.close()
            if code == 429:
                _cool_down(key, model)

    return None, None


def audio_message(chunk: bytes) -> str:
    return json.dumps(
        {"realtimeInput": {"audio": {"data": base64.b64encode(chunk).decode("ascii"), "mimeType": _VOICE_MIME}}}
    )


def control_message(kind: str) -> str:
    if kind == "start":
        return json.dumps({"realtimeInput": {"activityStart": {}}})
    return json.dumps({"realtimeInput": {"activityEnd": {}}})
