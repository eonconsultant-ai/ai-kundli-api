import pytest

from app.core.config import Settings
from app.schemas.ai import ChatMessage
from app.services.ai import chat as chat_module
from app.services.ai import groq
from app.services.astro.chart import build_kundli


def _kundli() -> dict:
    from datetime import date, time

    return build_kundli(
        birth_date=date(1990, 1, 1),
        birth_time=time(12, 0),
        tz_name="Asia/Kolkata",
        latitude=28.6139,
        longitude=77.2090,
        name=None,
        place_name=None,
    )


class _Response:
    def __init__(self, status: int, payload: dict | None = None, text: str = ""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


@pytest.fixture(autouse=True)
def _clear_cooldowns():
    groq._cooling_until.clear()
    yield
    groq._cooling_until.clear()


def _settings(**overrides) -> Settings:
    values = {"groq_api_key": "g1", "groq_model": "test-model"}
    values.update(overrides)
    return Settings(**values)


def test_groq_completion_returns_reply(monkeypatch):
    seen: dict = {}

    def fake_post(self, url, headers=None, json=None):
        seen["url"] = url
        seen["auth"] = headers["authorization"]
        seen["body"] = json
        return _Response(200, {"choices": [{"message": {"content": " Try service. "}}]})

    monkeypatch.setattr("httpx.Client.post", fake_post)
    result = groq.chat_completion(
        _settings(), system="Be kind.", messages=[{"role": "user", "content": "Hi"}], max_tokens=200
    )

    assert result == ("Try service.", "test-model")
    assert seen["url"].endswith("/chat/completions")
    assert seen["auth"] == "Bearer g1"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "Be kind."}
    assert seen["body"]["max_tokens"] == 200


def test_groq_rate_limit_parks_the_key(monkeypatch):
    calls: list[str] = []

    def fake_post(self, url, headers=None, json=None):
        calls.append(headers["authorization"])
        return _Response(429, text="rate limit")

    monkeypatch.setattr("httpx.Client.post", fake_post)
    settings = _settings(groq_api_key="g1", groq_api_keys="g2")

    assert groq.chat_completion(settings, system="s", messages=[], max_tokens=100) is None
    assert calls == ["Bearer g1", "Bearer g2"]
    assert groq.chat_completion(settings, system="s", messages=[], max_tokens=100) is None
    assert calls == ["Bearer g1", "Bearer g2"]


def test_groq_is_skipped_without_a_key(monkeypatch):
    def fake_post(*args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("no request expected")

    monkeypatch.setattr("httpx.Client.post", fake_post)
    assert groq.chat_completion(Settings(), system="s", messages=[], max_tokens=100) is None


def test_chat_falls_back_to_groq_when_gemini_fails(monkeypatch):
    monkeypatch.setattr(chat_module, "generate_content", lambda settings, body: None)
    monkeypatch.setattr(chat_module, "chat_completion", lambda *a, **k: ("Groq guidance.", "test-model"))

    reply = chat_module.chat_reply(
        _settings(gemini_api_key="k"),
        _kundli(),
        messages=[ChatMessage(role="user", content="Career?")],
        language="en",
        use_provider=True,
        use_search=True,
    )

    assert reply["source"] == "groq"
    assert reply["reply"] == "Groq guidance."


def test_chat_falls_back_to_chart_when_both_providers_fail(monkeypatch):
    monkeypatch.setattr(chat_module, "generate_content", lambda settings, body: None)
    monkeypatch.setattr(chat_module, "chat_completion", lambda *a, **k: None)

    reply = chat_module.chat_reply(
        _settings(gemini_api_key="k"),
        _kundli(),
        messages=[ChatMessage(role="user", content="Career?")],
        language="en",
    )

    assert reply["source"] == "chart"
    assert reply["reply"]
