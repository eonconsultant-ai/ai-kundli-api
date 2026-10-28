import pytest

from app.core.config import Settings
from app.schemas.ai import ChatMessage
from app.services.ai import chat as chat_module
from app.services.ai import gemini


class _Response:
    def __init__(self, status: int, payload: dict | None = None, text: str = ""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


@pytest.fixture(autouse=True)
def _clear_cooldowns():
    gemini._cooling_until.clear()
    yield
    gemini._cooling_until.clear()


def test_search_tool_is_retried_without_tools(monkeypatch):
    calls: list[bool] = []

    def fake_post(settings, key, model, body):
        calls.append("tools" in body)
        if "tools" in body:
            return _Response(400, text="Google Search grounding is not supported for this model.")
        return _Response(200, {"candidates": []})

    monkeypatch.setattr(gemini, "_post", fake_post)
    settings = Settings(gemini_api_key="k", gemini_model="m1", gemini_fallback_models="m2")

    result = gemini.generate_content(settings, {"contents": [], "tools": [{"google_search": {}}]})

    assert result is not None
    assert result[1] == "m1"
    assert calls == [True, False]


def test_grounding_quota_is_retried_without_tools(monkeypatch):
    calls: list[bool] = []

    def fake_post(settings, key, model, body):
        calls.append("tools" in body)
        if "tools" in body:
            return _Response(429, text="Resource exhausted")
        return _Response(200, {"candidates": []})

    monkeypatch.setattr(gemini, "_post", fake_post)
    settings = Settings(gemini_api_key="k", gemini_model="m1", gemini_fallback_models="m2")

    result = gemini.generate_content(settings, {"contents": [], "tools": [{"google_search": {}}]})

    assert result is not None
    assert result[1] == "m1"
    assert calls == [True, False]
    assert gemini._cooling_until == {}


def test_rate_limited_key_falls_through_to_next_key(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_post(settings, key, model, body):
        calls.append((model, key))
        if key == "k1":
            return _Response(429, text="Resource exhausted")
        return _Response(200, {"candidates": []})

    monkeypatch.setattr(gemini, "_post", fake_post)
    settings = Settings(gemini_api_key="k1", gemini_api_keys="k2", gemini_model="m1")

    result = gemini.generate_content(settings, {"contents": []})
    assert result is not None
    assert result[1] == "m1"
    assert calls == [("m1", "k1"), ("m1", "k2")]

    calls.clear()
    gemini.generate_content(settings, {"contents": []})
    assert calls == [("m1", "k2")]


def test_quota_on_every_key_moves_to_the_fallback_model(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_post(settings, key, model, body):
        calls.append((model, key))
        if model == "m1":
            return _Response(429, text="Resource exhausted")
        return _Response(200, {"candidates": []})

    monkeypatch.setattr(gemini, "_post", fake_post)
    settings = Settings(
        gemini_api_key="k1",
        gemini_api_keys="k2",
        gemini_model="m1",
        gemini_fallback_models="m2",
    )

    result = gemini.generate_content(settings, {"contents": []})
    assert result is not None
    assert result[1] == "m2"
    assert calls == [("m1", "k1"), ("m1", "k2"), ("m2", "k1")]


def test_chat_attaches_search_tool_only_when_asked(monkeypatch):
    captured: dict = {}

    def fake_generate(settings, body):
        captured["body"] = body
        return {"candidates": [{"content": {"parts": [{"text": "Hari OM. Guidance."}]}}]}, "m1"

    monkeypatch.setattr(chat_module, "generate_content", fake_generate)
    messages = [ChatMessage(role="user", content="Namaste")]
    facts = {"lagna": {"sign": "Pisces"}}

    enabled = chat_module._gemini_reply(Settings(gemini_api_key="k"), facts, messages, "en", True)
    assert enabled is not None
    assert enabled[0].startswith("Hari OM")
    assert captured["body"]["tools"] == [{"google_search": {}}]

    chat_module._gemini_reply(Settings(gemini_api_key="k"), facts, messages, "en", False)
    assert "tools" not in captured["body"]
