from fastapi.testclient import TestClient

from app.api.v1 import ai as ai_api
from app.core.config import Settings
from app.main import app
from app.services.ai import live

client = TestClient(app)

BIRTH = {
    "birth_date": "1990-01-01",
    "birth_time": "12:00:00",
    "timezone": "Asia/Kolkata",
    "latitude": 28.6139,
    "longitude": 77.2090,
}
INSTALL = "voice-install-0001"


def _settings(tmp_path, **overrides) -> Settings:
    values = {
        "gemini_api_key": "test-key",
        "ai_usage_db_path": tmp_path / "usage.db",
        "live_free_daily_turns": 4,
        "live_plus_daily_turns": 10,
        "ai_global_daily_budget": 100,
    }
    values.update(overrides)
    return Settings(**values)


def _live_body() -> dict:
    return {
        **BIRTH,
        "language": "en",
        "history": [
            {"role": "user", "content": "Hari Om"},
            {"role": "assistant", "content": "Hari OM. How may I guide you?"},
        ],
    }


def test_live_session_reserves_a_turn(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.setattr(ai_api, "get_settings", lambda: settings)

    response = client.post("/v1/ai/live/session", json=_live_body(), headers={"X-Install-Id": INSTALL})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token"]
    assert body["stream_path"] == "/v1/ai/live/stream"
    assert body["model_chain"] == ["gemini-3.8-live", "gemini-3.1-flash-live-preview"]
    assert body["live_quota"]["limit"] == 4
    assert body["live_quota"]["remaining"] == 3


def test_live_session_blocks_after_daily_turns(tmp_path, monkeypatch):
    settings = _settings(tmp_path, live_free_daily_turns=2)
    monkeypatch.setattr(ai_api, "get_settings", lambda: settings)

    for expected in (1, 0):
        response = client.post("/v1/ai/live/session", json=_live_body(), headers={"X-Install-Id": INSTALL})
        assert response.status_code == 200, response.text
        assert response.json()["live_quota"]["remaining"] == expected

    blocked = client.post("/v1/ai/live/session", json=_live_body(), headers={"X-Install-Id": INSTALL})
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "live_quota_exhausted"
    assert blocked.json()["live_quota"]["remaining"] == 0


def test_live_quota_is_reported_separately(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.setattr(ai_api, "get_settings", lambda: settings)

    body = client.get("/v1/ai/quota", headers={"X-Install-Id": INSTALL}).json()
    assert body["limit"] == 5
    assert body["live"]["limit"] == 4
    assert body["live"]["remaining"] == 4
    assert body["live"]["enforced"] is True


def test_live_session_requires_provider(tmp_path, monkeypatch):
    settings = _settings(tmp_path, gemini_api_key=None)
    monkeypatch.setattr(ai_api, "get_settings", lambda: settings)

    response = client.post("/v1/ai/live/session", json=_live_body(), headers={"X-Install-Id": INSTALL})
    assert response.status_code == 503
    assert response.json()["code"] == "ai_unavailable"


def test_expired_token_gives_the_turn_back(tmp_path, monkeypatch):
    settings = _settings(tmp_path, live_session_token_ttl_seconds=0)
    monkeypatch.setattr(ai_api, "get_settings", lambda: settings)

    body = client.post("/v1/ai/live/session", json=_live_body(), headers={"X-Install-Id": INSTALL}).json()
    assert body["live_quota"]["remaining"] == 3

    live.prune_expired(settings)
    quota = client.get("/v1/ai/quota", headers={"X-Install-Id": INSTALL}).json()
    assert quota["live"]["remaining"] == 4


def test_stream_rejects_unknown_token(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.setattr(ai_api, "get_settings", lambda: settings)

    with client.websocket_connect("/v1/ai/live/stream?token=not-a-token") as socket:
        assert socket.receive_json()["code"] == "session_expired"


def test_stream_refunds_when_provider_is_unreachable(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.setattr(ai_api, "get_settings", lambda: settings)

    async def no_connect(*args, **kwargs):
        return None, None

    monkeypatch.setattr(live, "connect_live", no_connect)

    token = client.post("/v1/ai/live/session", json=_live_body(), headers={"X-Install-Id": INSTALL}).json()["token"]
    with client.websocket_connect(f"/v1/ai/live/stream?token={token}") as socket:
        error = socket.receive_json()
    assert error["code"] == "unavailable"
    assert error["live_quota"]["remaining"] == 4

    quota = client.get("/v1/ai/quota", headers={"X-Install-Id": INSTALL}).json()
    assert quota["live"]["remaining"] == 4


def test_live_url_has_one_version_segment():
    url = live._live_url(Settings(gemini_api_key="test-key"))
    assert url == (
        "wss://generativelanguage.googleapis.com/ws/"
        "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
    )


def test_setup_message_uses_the_hindi_sage_voice():
    settings = Settings(gemini_api_key="test-key")
    setup = live._setup_message(settings, "gemini-3.8-live", "facts")["setup"]
    speech = setup["generationConfig"]["speechConfig"]
    assert setup["model"] == "models/gemini-3.8-live"
    assert speech["languageCode"] == "hi-IN"
    assert speech["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Charon"
    assert setup["realtimeInputConfig"]["automaticActivityDetection"]["disabled"] is True


def test_system_prompt_carries_facts_and_history_only():
    system = live.build_system({"lagna": {"sign": "Leo"}}, "en", [{"role": "user", "content": "Career?"}])
    assert 'Do not say "Hari OM" again' in system
    assert "Leo" in system
    assert "User: Career?" in system
    assert "1990-01-01" not in system


def test_first_turn_greets_with_hari_om():
    system = live.build_system({}, "hi", [])
    assert 'open it with the greeting "Hari OM"' in system
    assert "Do not say" not in system


def test_default_app_language_still_starts_in_hindi():
    system = live.build_system({}, "en", [])
    assert "Hindi is still your default" in system
