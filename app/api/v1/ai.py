import asyncio
import base64
import contextlib
import logging
from typing import Annotated

from fastapi import APIRouter, Header, Request, WebSocket
from fastapi.responses import JSONResponse

from app.api.v1.identity import install_id as resolve_install_id
from app.core.config import get_settings
from app.schemas.ai import AiChatRequest, AiLiveSessionRequest, AiReadingRequest, AiReportRequest
from app.services.ai import live, store
from app.services.ai.chat import chat_reply
from app.services.ai.reading import ai_status, build_facts, generate_reading
from app.services.astro.chart import build_kundli

router = APIRouter(tags=["ai"])
logger = logging.getLogger("jyotish.ai.live")


def _entitlement(install_id: str):
    settings = get_settings()
    return store.get(settings).entitlement(install_id)


def _quota(install_id: str, plus: bool, enforced: bool) -> dict:
    settings = get_settings()
    limit = settings.ai_plus_daily_messages if plus else settings.ai_free_daily_messages
    return store.get(settings).quota(
        install_id,
        limit=limit,
        plus=plus,
        enforced=enforced,
    )


def _live_quota(install_id: str, plus: bool, enforced: bool) -> dict:
    settings = get_settings()
    limit = settings.live_plus_daily_turns if plus else settings.live_free_daily_turns
    return store.get(settings).live_quota(
        install_id,
        limit=limit,
        plus=plus,
        enforced=enforced,
    )


def _live_limit_response(install_id: str, plus: bool) -> JSONResponse:
    quota = _live_quota(install_id, plus, True)
    message = (
        "Daily voice fair-use limit reached. Please continue tomorrow."
        if plus
        else "Daily free voice limit reached. Subscribe to AI Kundli Plus for more voice turns."
    )
    return JSONResponse(
        status_code=429,
        content={"detail": message, "code": "live_quota_exhausted", "live_quota": quota},
    )


def _limit_response(install_id: str, plus: bool) -> JSONResponse:
    quota = _quota(install_id, plus, True)
    message = (
        "Daily AI fair-use limit reached. Please continue tomorrow."
        if plus
        else "Daily free AI question limit reached. Subscribe to AI Kundli Plus for more."
    )
    return JSONResponse(
        status_code=429,
        content={"detail": message, "code": "quota_exhausted", "quota": quota},
    )


@router.get("/ai/status", summary="Whether a language model is configured")
def status() -> dict:
    settings = get_settings()
    body = ai_status(settings)
    body["plus_product_id"] = settings.plus_product_id
    body["voice_enabled"] = bool(settings.gemini_keys)
    body["live_models"] = settings.gemini_live_models if settings.gemini_keys else []
    body["free_daily_voice_turns"] = settings.live_free_daily_turns
    body["plus_daily_voice_turns"] = settings.live_plus_daily_turns
    return body


@router.get("/ai/quota", summary="Remaining AI messages and voice turns for this install")
def quota(
    request: Request,
    x_install_id: Annotated[str | None, Header(alias="X-Install-Id")] = None,
) -> dict:
    settings = get_settings()
    install_id = resolve_install_id(x_install_id, request)
    plus = _entitlement(install_id) is not None
    enforced = settings.text_provider_configured
    body = _quota(install_id, plus, enforced)
    body["live"] = _live_quota(install_id, plus, enforced)
    return body


@router.post("/ai/kundli-reading", summary="Personalised reading and remedies for a Kundli")
def kundli_reading(payload: AiReadingRequest) -> dict:
    settings = get_settings()
    usage = store.get(settings)
    kundli = build_kundli(
        birth_date=payload.birth_date,
        birth_time=payload.birth_time,
        tz_name=payload.timezone,
        latitude=payload.latitude,
        longitude=payload.longitude,
        name=None,
        place_name=None,
        altitude_m=payload.altitude_m,
        ayanamsa=payload.ayanamsa,
        node_mode=payload.node_mode,
        include_pratyantar=False,
    )
    use_provider = bool(settings.gemini_keys) and usage.consume_global(settings.ai_global_daily_budget)
    result = generate_reading(
        settings,
        kundli,
        focus=payload.focus,
        language=payload.language,
        daily=payload.daily,
        use_provider=use_provider,
    )
    if use_provider and result["source"] == "chart":
        usage.refund_global()
    result["budget_exhausted"] = bool(settings.gemini_keys) and not use_provider
    return result


@router.post("/ai/kundli-chat", summary="Ask AI Jyotish about a Kundli")
def kundli_chat(
    payload: AiChatRequest,
    request: Request,
    x_install_id: Annotated[str | None, Header(alias="X-Install-Id")] = None,
) -> dict:
    settings = get_settings()
    usage = store.get(settings)
    install_id = resolve_install_id(x_install_id, request)
    plus = _entitlement(install_id) is not None
    enforced = settings.text_provider_configured

    if enforced and _quota(install_id, plus, True)["remaining"] <= 0:
        return _limit_response(install_id, plus)

    kundli = build_kundli(
        birth_date=payload.birth_date,
        birth_time=payload.birth_time,
        tz_name=payload.timezone,
        latitude=payload.latitude,
        longitude=payload.longitude,
        name=None,
        place_name=None,
        altitude_m=payload.altitude_m,
        ayanamsa=payload.ayanamsa,
        node_mode=payload.node_mode,
        include_pratyantar=False,
    )

    use_provider = enforced
    budget_exhausted = False
    used_today = 0
    if enforced:
        if not usage.consume_global(settings.ai_global_daily_budget):
            use_provider = False
            budget_exhausted = True
        else:
            limit = settings.ai_plus_daily_messages if plus else settings.ai_free_daily_messages
            consumed = usage.consume_message(install_id, limit)
            if consumed is None:
                usage.refund_global()
                return _limit_response(install_id, plus)
            used_today = consumed

    # Grounding is billed per request, far above the token cost, so free installs
    # get it on their first messages of the day; Plus is capped by its quota only.
    use_search = False
    if use_provider and settings.gemini_enable_search:
        use_search = plus or (
            settings.ai_free_grounded_messages > 0
            and used_today <= settings.ai_free_grounded_messages
        )

    result = chat_reply(
        settings,
        kundli,
        messages=payload.messages,
        language=payload.language,
        use_provider=use_provider,
        use_search=use_search,
    )

    if use_provider and result["source"] == "chart":
        # The provider failed; do not charge the user's daily quota.
        usage.refund_message(install_id)
        usage.refund_global()

    result["quota"] = _quota(install_id, plus, enforced)
    result["budget_exhausted"] = budget_exhausted
    result["search_grounded"] = use_search
    return result


@router.post(
    "/ai/live/session",
    summary="Reserve one voice turn and mint a session token",
    response_model=None,
)
def live_session(
    payload: AiLiveSessionRequest,
    request: Request,
    x_install_id: Annotated[str | None, Header(alias="X-Install-Id")] = None,
) -> dict | JSONResponse:
    settings = get_settings()
    usage = store.get(settings)
    install_id = resolve_install_id(x_install_id, request)
    plus = _entitlement(install_id) is not None
    enforced = bool(settings.gemini_keys)

    if not enforced:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "AI voice is not configured on this server. Text chat still works.",
                "code": "ai_unavailable",
            },
        )

    if _live_quota(install_id, plus, True)["remaining"] <= 0:
        return _live_limit_response(install_id, plus)

    if not usage.consume_global(settings.ai_global_daily_budget):
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Voice is taking a short break. Please try again later.",
                "code": "budget_exhausted",
            },
        )

    limit = settings.live_plus_daily_turns if plus else settings.live_free_daily_turns
    if usage.consume_live_turn(install_id, limit) is None:
        usage.refund_global()
        return _live_limit_response(install_id, plus)

    kundli = build_kundli(
        birth_date=payload.birth_date,
        birth_time=payload.birth_time,
        tz_name=payload.timezone,
        latitude=payload.latitude,
        longitude=payload.longitude,
        name=None,
        place_name=None,
        altitude_m=payload.altitude_m,
        ayanamsa=payload.ayanamsa,
        node_mode=payload.node_mode,
        include_pratyantar=False,
    )
    facts = build_facts(kundli, "life")
    session = live.new_session(
        settings,
        install_id=install_id,
        plus=plus,
        facts=facts,
        language=payload.language,
        history=[message.model_dump() for message in payload.history],
    )
    return {
        "token": session.token,
        "stream_path": f"{settings.api_v1_prefix}/ai/live/stream",
        "model_chain": settings.gemini_live_models,
        "voice": settings.live_voice_name,
        "language": payload.language,
        "max_seconds": settings.live_max_seconds,
        "expires_in": settings.live_session_token_ttl_seconds,
        "live_quota": _live_quota(install_id, plus, enforced),
        "privacy": live.LIVE_PRIVACY,
    }


@router.websocket("/ai/live/stream")
async def live_stream(websocket: WebSocket, token: str = "") -> None:
    """Proxy one push-to-talk turn to Gemini Live without exposing the API key."""
    settings = get_settings()
    await websocket.accept()

    session = live.take_session(settings, token)
    if session is None:
        await websocket.send_json({"type": "error", "code": "session_expired"})
        await websocket.close()
        return

    system = live.build_system(session.facts, session.language, session.history)
    socket, model = await live.connect_live(settings, system)
    if socket is None:
        live.refund_session(settings, session)
        await websocket.send_json(
            {
                "type": "error",
                "code": "unavailable",
                # The turn was just given back; tell the client so the strip does
                # not keep showing a used turn for a call that never happened.
                "live_quota": _live_quota(session.install_id, session.plus, True),
            }
        )
        await websocket.close()
        return

    live.mark_used(session, model)
    await websocket.send_json({"type": "ready", "model": model, "max_seconds": settings.live_max_seconds})
    await socket.send(live.control_message("start"))

    async def client_to_google() -> None:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            chunk = message.get("bytes")
            if chunk:
                await socket.send(live.audio_message(chunk))
                continue
            text = message.get("text")
            data = live._json_frame(text) if text else None
            if data and data.get("type") == "end":
                # Keep draining: Google still has to speak the answer, and
                # google_to_client ends the turn on turnComplete.
                await socket.send(live.control_message("end"))

    async def google_to_client() -> None:
        while True:
            raw = await socket.recv()
            data = live._json_frame(raw)
            if data is None:
                continue
            server = data.get("serverContent") or {}
            for part in (server.get("modelTurn") or {}).get("parts") or []:
                inline = part.get("inlineData") or {}
                if inline.get("data"):
                    await websocket.send_bytes(base64.b64decode(inline["data"]))
            for key, role in (("outputTranscription", "assistant"), ("inputTranscription", "user")):
                text = (server.get(key) or {}).get("text")
                if text:
                    await websocket.send_json({"type": "transcript", "role": role, "text": text})
            if server.get("interrupted"):
                await websocket.send_json({"type": "interrupted"})
            if server.get("turnComplete") or data.get("goAway"):
                await websocket.send_json({"type": "turn_complete"})
                return

    tasks = [asyncio.create_task(client_to_google()), asyncio.create_task(google_to_client())]
    try:
        done, pending = await asyncio.wait(
            tasks,
            timeout=settings.live_max_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        results = await asyncio.gather(*pending, *done, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                logger.info("Live proxy stopped: %s", result)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await socket.close()
        with contextlib.suppress(Exception):
            await websocket.send_json(
                {"type": "closed", "live_quota": _live_quota(session.install_id, session.plus, True)}
            )
        # The app may already have closed the socket after turn_complete.
        with contextlib.suppress(Exception):
            await websocket.close()


@router.post("/ai/report", status_code=202, summary="Report an unsafe or inaccurate AI reply")
def report_reply(
    payload: AiReportRequest,
    request: Request,
    x_install_id: Annotated[str | None, Header(alias="X-Install-Id")] = None,
) -> dict:
    install_id = resolve_install_id(x_install_id, request)
    settings = get_settings()
    store.get(settings).record_report(
        install_id=install_id,
        reason=payload.reason,
        question=payload.question,
        reply=payload.reply,
    )
    return {"status": "received"}
