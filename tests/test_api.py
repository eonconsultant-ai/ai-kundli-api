from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_engine_meta():
    response = client.get("/v1/engine/meta")
    assert response.status_code == 200
    body = response.json()
    assert "D9" in body["vargas"]
    assert "lahiri" in body["ayanamsas"]


def test_compute_kundli():
    response = client.post(
        "/v1/kundli/compute",
        json={
            "name": "Reference Chart",
            "birth_date": "1990-01-01",
            "birth_time": "12:00:00",
            "timezone": "Asia/Kolkata",
            "latitude": 28.6139,
            "longitude": 77.2090,
            "place_name": "New Delhi",
            "include_pratyantar": False,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["lagna"]["sign"] == "Pisces"
    assert body["moon_sign"]["sign"] == "Aquarius"
    assert len(body["planets"]) == 9
    assert body["dashas"]["mahadashas"]
    assert body["engine"]["ayanamsa"] == "lahiri"


def test_invalid_timezone_is_rejected():
    response = client.post(
        "/v1/kundli/compute",
        json={
            "birth_date": "1990-01-01",
            "birth_time": "12:00:00",
            "timezone": "Asia/Nowhere",
            "latitude": 28.6139,
            "longitude": 77.2090,
        },
    )
    assert response.status_code == 422


def test_panchang_endpoint():
    response = client.get(
        "/v1/panchang",
        params={
            "date": "2024-01-01",
            "latitude": 28.6139,
            "longitude": 77.2090,
            "timezone": "Asia/Kolkata",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tithi"]["name"] == "Panchami"
    assert body["vara"]["name"] == "Monday"
    assert body["kaal"]["rahu"]["start"].startswith("2024-01-01T08:31")


def test_matching_compute():
    response = client.post(
        "/v1/matching/compute",
        json={
            "bride": {
                "name": "Bride",
                "birth_date": "1990-01-01",
                "birth_time": "12:00:00",
                "timezone": "Asia/Kolkata",
                "latitude": 28.6139,
                "longitude": 77.2090,
                "place_name": "New Delhi",
            },
            "groom": {
                "name": "Groom",
                "birth_date": "1992-05-15",
                "birth_time": "09:30:00",
                "timezone": "Asia/Kolkata",
                "latitude": 19.0760,
                "longitude": 72.8777,
                "place_name": "Mumbai",
            },
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["bride"]["moon_sign"] == "Aquarius"
    assert len(body["ashtakoot"]["items"]) == 8
    assert body["ashtakoot"]["total"] == sum(
        item["score"] for item in body["ashtakoot"]["items"]
    )
    assert body["ashtakoot"]["total"] <= 36
    assert body["lagna_match"]["max"] == 10
    assert body["mangal_dosha"]["status"] in {
        "both_manglik",
        "both_non_manglik",
        "bride_manglik",
        "groom_manglik",
    }


def test_matching_rejects_unknown_system():
    response = client.post(
        "/v1/matching/compute",
        json={
            "bride": {
                "birth_date": "1990-01-01",
                "birth_time": "12:00:00",
                "timezone": "Asia/Kolkata",
                "latitude": 28.6139,
                "longitude": 77.2090,
            },
            "groom": {
                "birth_date": "1992-05-15",
                "birth_time": "09:30:00",
                "timezone": "Asia/Kolkata",
                "latitude": 19.0760,
                "longitude": 72.8777,
            },
            "systems": ["ashtakoot", "numerology"],
        },
    )
    assert response.status_code == 422
