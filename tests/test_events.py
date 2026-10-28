from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.api.v1 import events as events_api
from app.core.config import Settings
from app.main import app
from app.services.ai import store

client = TestClient(app)


def _settings(tmp_path, **overrides) -> Settings:
    values = {"ai_usage_db_path": tmp_path / "usage.db"}
    values.update(overrides)
    return Settings(**values)


def test_events_endpoint_counts_events_and_labels(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.setattr(events_api, "get_settings", lambda: settings)

    payload = {
        "events": [
            {"name": "app_open"},
            {"name": "screen_view", "label": "kundli"},
            {"name": "screen_view", "label": "kundli"},
            {"name": "rewarded_earned", "label": "ai_kundli_chat"},
        ]
    }
    response = client.post(
        "/v1/events", json=payload, headers={"X-Install-Id": "events-install-0001"}
    )
    assert response.status_code == 202, response.text
    assert response.json() == {"accepted": 4}

    body = store.get(settings).activity(7)
    today = body["days"][-1]
    assert today["active_installs"] == 1
    assert today["events"] == {"app_open": 1, "screen_view": 2, "rewarded_earned": 1}
    assert today["labels"] == {"kundli": 2, "ai_kundli_chat": 1}
    assert body["totals"]["events"]["app_open"] == 1


def test_unknown_events_and_labels_are_rejected(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.setattr(events_api, "get_settings", lambda: settings)

    unknown_name = client.post("/v1/events", json={"events": [{"name": "birth_details"}]})
    assert unknown_name.status_code == 422

    unknown_label = client.post(
        "/v1/events", json={"events": [{"name": "app_open", "label": "1990-01-01"}]}
    )
    assert unknown_label.status_code == 422

    invalid_shape = client.post("/v1/events", json={"events": []})
    assert invalid_shape.status_code == 422


def test_summary_needs_a_configured_token(tmp_path, monkeypatch):
    disabled = _settings(tmp_path)
    monkeypatch.setattr(events_api, "get_settings", lambda: disabled)
    assert client.get("/v1/events/summary").status_code == 404

    enabled = _settings(tmp_path, analytics_token="s3cret")
    monkeypatch.setattr(events_api, "get_settings", lambda: enabled)
    assert client.get("/v1/events/summary").status_code == 401
    assert (
        client.get("/v1/events/summary", headers={"X-Analytics-Token": "wrong"}).status_code
        == 401
    )

    accepted = client.get(
        "/v1/events/summary",
        params={"days": 3},
        headers={"X-Analytics-Token": "s3cret"},
    )
    assert accepted.status_code == 200, accepted.text
    assert len(accepted.json()["days"]) == 3


def test_daily_cap_stops_a_runaway_client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ACTIVITY_DAILY_CAP", 3)
    sqlite = store.SqliteStore(tmp_path / "cap.db")
    install = "cap-install-000001"

    assert sqlite.record_events(install, [("app_open", None)] * 2) == 2
    assert sqlite.record_events(install, [("app_open", None)] * 5) == 1
    assert sqlite.record_events(install, [("app_open", None)]) == 0


def test_activity_windows_days_and_keeps_only_recent_counters(tmp_path):
    sqlite = store.SqliteStore(tmp_path / "days.db")
    now = datetime(2026, 10, 27, 6, 0, tzinfo=UTC)

    sqlite.record_events(
        "install-0000001",
        [("app_open", None), ("screen_view", "kundli")],
        now=now,
    )
    sqlite.record_events(
        "install-0000002",
        [("app_open", None)],
        now=now - timedelta(days=40),
    )

    body = sqlite.activity(7, now=now)
    today = body["days"][-1]
    assert today["day"] == "2026-10-27"
    assert today["active_installs"] == 1
    assert today["events"] == {"app_open": 1, "screen_view": 1}
    assert today["labels"] == {"kundli": 1}
    assert len(body["days"]) == 7
    assert body["totals"]["active_installs"] == 1

    sqlite.prune(now=now)
    assert sqlite.activity(60, now=now)["totals"]["active_installs"] == 1


def test_activity_includes_ai_usage_and_active_subscriptions(tmp_path):
    sqlite = store.SqliteStore(tmp_path / "mixed.db")
    sqlite.consume_message("install-0000001", 5)
    sqlite.grant_plus(
        "install-0000001",
        expires_at="2030-01-01T00:00:00+00:00",
        source="test",
    )

    body = sqlite.activity(1)
    assert body["days"][-1]["ai_messages"] == 1
    assert body["days"][-1]["ai_voice_turns"] == 0
    assert body["plus_active"] == 1
