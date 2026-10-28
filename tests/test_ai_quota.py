import sqlite3
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.api.v1 import ai as ai_api
from app.api.v1 import billing as billing_api
from app.core.config import Settings
from app.main import app
from app.services.ai import store

client = TestClient(app)

BIRTH = {
    "birth_date": "1990-01-01",
    "birth_time": "12:00:00",
    "timezone": "Asia/Kolkata",
    "latitude": 28.6139,
    "longitude": 77.2090,
}
INSTALL = "test-install-0001"


def _settings(tmp_path, **overrides) -> Settings:
    values = {
        "gemini_api_key": "test-key",
        "ai_usage_db_path": tmp_path / "usage.db",
        "ai_free_daily_messages": 2,
        "ai_plus_daily_messages": 10,
        "ai_global_daily_budget": 100,
    }
    values.update(overrides)
    return Settings(**values)


def _chat_body(text: str = "What about my career?") -> dict:
    return {**BIRTH, "language": "en", "messages": [{"role": "user", "content": text}]}


def _fake_chat_reply(settings, kundli, *, messages, language, use_provider=True, use_search=False):
    return {
        "source": "gemini" if use_provider else "chart",
        "model": "fake-model" if use_provider else None,
        "language": language,
        "reply": "A grounded answer.",
        "disclaimer": "not a prediction",
        "privacy": "facts only",
        "generated_at": "2026-10-27T00:00:00+00:00",
    }


def _recording_chat_reply(grounded: list[bool]):
    def fake(settings, kundli, *, messages, language, use_provider=True, use_search=False):
        grounded.append(use_search)
        return _fake_chat_reply(settings, kundli, messages=messages, language=language)

    return fake


def test_free_chat_grounds_only_the_first_messages(tmp_path, monkeypatch):
    settings = _settings(tmp_path, ai_free_daily_messages=3, ai_free_grounded_messages=1)
    monkeypatch.setattr(ai_api, "get_settings", lambda: settings)
    grounded: list[bool] = []
    monkeypatch.setattr(ai_api, "chat_reply", _recording_chat_reply(grounded))
    install = "grounding-free-0001"

    for _ in range(3):
        response = client.post("/v1/ai/kundli-chat", json=_chat_body(), headers={"X-Install-Id": install})
        assert response.status_code == 200, response.text

    assert grounded == [True, False, False]
    assert response.json()["search_grounded"] is False


def test_plus_chat_keeps_grounding_on_every_message(tmp_path, monkeypatch):
    settings = _settings(tmp_path, ai_free_grounded_messages=1)
    monkeypatch.setattr(ai_api, "get_settings", lambda: settings)
    grounded: list[bool] = []
    monkeypatch.setattr(ai_api, "chat_reply", _recording_chat_reply(grounded))
    install = "grounding-plus-0001"
    store.get(settings).grant_plus(install, expires_at="2030-01-01T00:00:00+00:00", source="test")

    for _ in range(2):
        response = client.post("/v1/ai/kundli-chat", json=_chat_body(), headers={"X-Install-Id": install})
        assert response.status_code == 200, response.text

    assert grounded == [True, True]


def test_free_quota_blocks_after_limit(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.setattr(ai_api, "get_settings", lambda: settings)
    monkeypatch.setattr(ai_api, "chat_reply", _fake_chat_reply)

    first = client.post("/v1/ai/kundli-chat", json=_chat_body(), headers={"X-Install-Id": INSTALL})
    assert first.status_code == 200, first.text
    assert first.json()["quota"]["remaining"] == 1

    second = client.post("/v1/ai/kundli-chat", json=_chat_body(), headers={"X-Install-Id": INSTALL})
    assert second.status_code == 200
    assert second.json()["quota"]["remaining"] == 0

    third = client.post("/v1/ai/kundli-chat", json=_chat_body(), headers={"X-Install-Id": INSTALL})
    assert third.status_code == 429
    body = third.json()
    assert body["code"] == "quota_exhausted"
    assert body["quota"]["remaining"] == 0


def test_plus_entitlement_gets_higher_limit(tmp_path, monkeypatch):
    settings = _settings(tmp_path, ai_free_daily_messages=1, ai_plus_daily_messages=3)
    monkeypatch.setattr(ai_api, "get_settings", lambda: settings)
    monkeypatch.setattr(ai_api, "chat_reply", _fake_chat_reply)
    store.get(settings).grant_plus(
        INSTALL,
        expires_at="2030-01-01T00:00:00+00:00",
        source="test",
    )

    for expected in (2, 1, 0):
        response = client.post("/v1/ai/kundli-chat", json=_chat_body(), headers={"X-Install-Id": INSTALL})
        assert response.status_code == 200, response.text
        assert response.json()["quota"]["plus"] is True
        assert response.json()["quota"]["remaining"] == expected

    blocked = client.post("/v1/ai/kundli-chat", json=_chat_body(), headers={"X-Install-Id": INSTALL})
    assert blocked.status_code == 429


def test_chat_quota_endpoint(tmp_path, monkeypatch):
    settings = _settings(tmp_path, ai_free_daily_messages=5)
    monkeypatch.setattr(ai_api, "get_settings", lambda: settings)

    body = client.get("/v1/ai/quota", headers={"X-Install-Id": INSTALL}).json()
    assert body["limit"] == 5
    assert body["remaining"] == 5
    assert body["enforced"] is True
    assert body["plus"] is False
    assert "resets_at" in body


def test_report_reply_is_accepted(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.setattr(ai_api, "get_settings", lambda: settings)
    response = client.post(
        "/v1/ai/report",
        json={"reason": "inaccurate", "question": "Career?", "reply": "A reply"},
        headers={"X-Install-Id": INSTALL},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "received"


def test_billing_verify_grants_plus(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.setattr(billing_api, "get_settings", lambda: settings)
    monkeypatch.setattr(
        billing_api,
        "verify_subscription",
        lambda settings, product_id, purchase_token: {
            "product_id": product_id,
            "state": "SUBSCRIPTION_STATE_ACTIVE",
            "expires_at": "2030-01-01T00:00:00+00:00",
            "purchase_token": purchase_token,
        },
    )

    response = client.post(
        "/v1/billing/google/verify",
        json={"product_id": settings.plus_product_id, "purchase_token": "purchase-token-123"},
        headers={"X-Install-Id": INSTALL},
    )
    assert response.status_code == 200, response.text
    assert response.json()["plus"] is True

    entitlement = client.get("/v1/billing/entitlement", headers={"X-Install-Id": INSTALL}).json()
    assert entitlement["plus"] is True
    assert entitlement["plan"] == "plus"


def test_billing_rejects_when_not_configured(tmp_path, monkeypatch):
    settings = _settings(tmp_path, google_play_service_account_json=None)
    monkeypatch.setattr(billing_api, "get_settings", lambda: settings)

    response = client.post(
        "/v1/billing/google/verify",
        json={"product_id": settings.plus_product_id, "purchase_token": "purchase-token-123"},
        headers={"X-Install-Id": INSTALL},
    )
    assert response.status_code == 503


def test_billing_requires_install_id(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.setattr(billing_api, "get_settings", lambda: settings)
    response = client.post(
        "/v1/billing/google/verify",
        json={"product_id": settings.plus_product_id, "purchase_token": "purchase-token-123"},
    )
    assert response.status_code == 400


def _age_stored_entitlement(path, install_id: str, *, days: int = 2) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE entitlements SET updated_at = ? WHERE install_id = ?",
            ((datetime.now(UTC) - timedelta(days=days)).isoformat(), install_id),
        )


def test_entitlement_refreshes_renewed_subscription(tmp_path, monkeypatch):
    settings = _settings(
        tmp_path,
        google_play_service_account_json='{"type": "service_account"}',
    )
    monkeypatch.setattr(billing_api, "get_settings", lambda: settings)
    install = "refresh-install-0001"
    store.get(settings).grant_plus(
        install,
        expires_at="2026-01-01T00:00:00+00:00",
        source="google_play",
        purchase_token="purchase-token-123",
    )
    _age_stored_entitlement(settings.ai_usage_db_path, install)

    calls: list[tuple[str, str]] = []

    def fake_verify(settings, *, product_id, purchase_token):
        calls.append((product_id, purchase_token))
        return {
            "product_id": product_id,
            "state": "SUBSCRIPTION_STATE_ACTIVE",
            "expires_at": "2030-01-01T00:00:00+00:00",
            "purchase_token": purchase_token,
        }

    monkeypatch.setattr(billing_api, "verify_subscription", fake_verify)

    body = client.get("/v1/billing/entitlement", headers={"X-Install-Id": install}).json()
    assert body["plus"] is True
    assert body["expires_at"] == "2030-01-01T00:00:00+00:00"
    assert calls == [(settings.plus_product_id, "purchase-token-123")]

    again = client.get("/v1/billing/entitlement", headers={"X-Install-Id": install}).json()
    assert again["plus"] is True
    assert len(calls) == 1


def test_entitlement_survives_failed_refresh(tmp_path, monkeypatch):
    settings = _settings(
        tmp_path,
        google_play_service_account_json='{"type": "service_account"}',
    )
    monkeypatch.setattr(billing_api, "get_settings", lambda: settings)
    install = "refresh-fail-0001"
    store.get(settings).grant_plus(
        install,
        expires_at="2030-01-01T00:00:00+00:00",
        source="google_play",
        purchase_token="purchase-token-456",
    )
    _age_stored_entitlement(settings.ai_usage_db_path, install)

    calls: list[str] = []

    def failing_verify(settings, *, product_id, purchase_token):
        calls.append(product_id)
        raise billing_api.BillingVerificationError("Google Play is unavailable.")

    monkeypatch.setattr(billing_api, "verify_subscription", failing_verify)

    body = client.get("/v1/billing/entitlement", headers={"X-Install-Id": install}).json()
    assert body["plus"] is True
    assert body["expires_at"] == "2030-01-01T00:00:00+00:00"

    client.get("/v1/billing/entitlement", headers={"X-Install-Id": install})
    assert len(calls) == 1
