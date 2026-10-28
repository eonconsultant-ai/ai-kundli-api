import json
from datetime import date, time

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services.ai import reading as reading_module
from app.services.ai.reading import build_facts, generate_reading
from app.services.astro.chart import build_kundli

client = TestClient(app)

BIRTH = {
    "birth_date": "1990-01-01",
    "birth_time": "12:00:00",
    "timezone": "Asia/Kolkata",
    "latitude": 28.6139,
    "longitude": 77.2090,
}


def test_ai_reading_without_key_uses_chart_source():
    response = client.post("/v1/ai/kundli-reading", json={**BIRTH, "language": "en"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "chart"
    assert body["language"] == "en"
    assert len(body["sections"]) == 4
    assert len(body["remedies"]) == 3
    assert body["affirmation"]
    assert "not a prediction" in body["disclaimer"]
    assert body["privacy"]


def test_ai_status_shape():
    body = client.get("/v1/ai/status").json()
    assert body["provider"] in {"gemini", "groq", "none"}
    assert isinstance(body["ai_configured"], bool)
    assert body["provider"] != "none" or body["ai_configured"] is False
    assert body["free_daily_grounded_messages"] >= 0


def test_ai_hindi_reading_uses_hindi_names():
    body = client.post(
        "/v1/ai/kundli-reading", json={**BIRTH, "language": "hi"}
    ).json()
    titles = [section["title"] for section in body["sections"]]
    assert "मूल स्वभाव" in titles
    assert "वर्तमान काल" in titles
    assert "Pisces" not in body["overview"]
    assert "मीन" in body["overview"]


def test_ai_relationships_focus_has_distinct_fourth_section():
    body = client.post(
        "/v1/ai/kundli-reading",
        json={**BIRTH, "language": "en", "focus": "relationships"},
    ).json()
    titles = [section["title"] for section in body["sections"]]
    assert titles[1] == "Relationships and home"
    assert titles[3] == "Work and direction"
    assert len(set(titles)) == len(titles)


def test_ai_rejects_unknown_focus():
    response = client.post(
        "/v1/ai/kundli-reading", json={**BIRTH, "focus": "lottery"}
    )
    assert response.status_code == 422


def test_ai_never_sends_birth_details(monkeypatch):
    kundli = build_kundli(
        birth_date=date(1990, 1, 1),
        birth_time=time(12, 0),
        tz_name=BIRTH["timezone"],
        latitude=BIRTH["latitude"],
        longitude=BIRTH["longitude"],
        name="Secret Name",
        place_name="Secretville",
    )
    captured: list[dict] = []

    def fake_gemini(settings, facts, language, daily):
        captured.append(facts)
        return (
            {
                "headline": "Headline",
                "overview": "Overview",
                "sections": [
                    {"title": "A", "body": "B"},
                    {"title": "C", "body": "D"},
                    {"title": "E", "body": "F"},
                ],
                "remedies": [{"title": "T", "practice": "P", "why": "W"}],
                "affirmation": "Act today.",
            },
            "fake-model",
        )

    monkeypatch.setattr(reading_module, "_gemini_reading", fake_gemini)
    result = generate_reading(
        get_settings(), kundli, focus="career", language="en"
    )

    assert result["source"] == "gemini"
    payload = json.dumps(captured[0])
    assert "Secret Name" not in payload
    assert "Secretville" not in payload
    assert "1990-01-01" not in payload
    assert "12:00:00" not in payload
    assert "latitude" not in captured[0]


def test_facts_have_no_birth_inputs():
    kundli = build_kundli(
        birth_date=date(1990, 1, 1),
        birth_time=time(12, 0),
        tz_name=BIRTH["timezone"],
        latitude=BIRTH["latitude"],
        longitude=BIRTH["longitude"],
        name="Secret Name",
        place_name="Secretville",
    )
    facts = build_facts(kundli, "life")
    serialized = json.dumps(facts)
    assert "Secret Name" not in serialized
    assert "Secretville" not in serialized
    assert BIRTH["latitude"] not in facts


def _chat(payload: dict):
    return client.post("/v1/ai/kundli-chat", json=payload)


def test_chat_fallback_answers_career_question():
    response = _chat(
        {
            **BIRTH,
            "language": "en",
            "messages": [{"role": "user", "content": "How is my career going to be?"}],
        }
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "chart"
    assert "tenth house" in body["reply"].lower()
    assert body["privacy"]
    assert "not a prediction" in body["disclaimer"]


def test_chat_hindi_remedies_answer():
    body = _chat(
        {
            **BIRTH,
            "language": "hi",
            "messages": [{"role": "user", "content": "मुझे कौन से उपाय करने चाहिए?"}],
        }
    ).json()
    assert body["source"] == "chart"
    assert "जाप" in body["reply"]
    assert "ॐ" in body["reply"]


def test_chat_uses_conversation_history():
    body = _chat(
        {
            **BIRTH,
            "language": "en",
            "messages": [
                {"role": "user", "content": "Tell me about my chart."},
                {"role": "assistant", "content": "Your Lagna is Pisces."},
                {"role": "user", "content": "What about marriage?"},
            ],
        }
    ).json()
    assert "seventh house" in body["reply"].lower()


def test_chat_rejects_last_assistant_message():
    response = _chat(
        {
            **BIRTH,
            "messages": [{"role": "assistant", "content": "Hello"}],
        }
    )
    assert response.status_code == 422


def test_chat_never_sends_birth_details(monkeypatch):
    from app.schemas.ai import ChatMessage
    from app.services.ai import chat as chat_module

    kundli = build_kundli(
        birth_date=date(1990, 1, 1),
        birth_time=time(12, 0),
        tz_name=BIRTH["timezone"],
        latitude=BIRTH["latitude"],
        longitude=BIRTH["longitude"],
        name="Secret Name",
        place_name="Secretville",
    )
    captured: list[dict] = []

    def fake_gemini(settings, facts, messages, language, use_search):
        captured.append(facts)
        return "Keep steady routines this month.", "fake-model"

    monkeypatch.setattr(chat_module, "_gemini_reply", fake_gemini)
    result = chat_module.chat_reply(
        get_settings(),
        kundli,
        messages=[ChatMessage(role="user", content="What about my career?")],
        language="en",
    )

    assert result["source"] == "gemini"
    assert result["reply"] == "Keep steady routines this month."
    payload = json.dumps(captured[0])
    assert "Secret Name" not in payload
    assert "Secretville" not in payload
    assert "1990-01-01" not in payload
