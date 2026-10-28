from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.ratelimit import RateLimitMiddleware, SlidingWindow


def _client(**kwargs) -> TestClient:
    app = FastAPI()

    @app.get("/v1/panchang")
    def panchang() -> dict:
        return {"ok": True}

    @app.get("/v1/ai/status")
    def ai_status() -> dict:
        return {"ok": True}

    @app.get("/v1/health")
    def health() -> dict:
        return {"ok": True}

    app.add_middleware(RateLimitMiddleware, **kwargs)
    return TestClient(app)


def test_window_allows_the_limit_then_reports_the_wait():
    window = SlidingWindow(2)
    assert window.retry_after("ip", now=100.0) is None
    assert window.retry_after("ip", now=100.5) is None
    assert window.retry_after("ip", now=101.0) == 60
    assert window.retry_after("ip", now=160.1) is None


def test_window_rolls_off_after_the_minute():
    window = SlidingWindow(1)
    assert window.retry_after("ip", now=0.0) is None
    assert window.retry_after("ip", now=30.0) == 31
    assert window.retry_after("ip", now=61.0) is None


def test_compute_limit_is_per_forwarded_address():
    client = _client(compute_limit=2)
    headers = {"X-Forwarded-For": "203.0.113.9"}
    assert client.get("/v1/panchang", headers=headers).status_code == 200
    assert client.get("/v1/panchang", headers=headers).status_code == 200

    blocked = client.get("/v1/panchang", headers=headers)
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "rate_limited"
    assert int(blocked.headers["retry-after"]) >= 1

    other = {"X-Forwarded-For": "198.51.100.4"}
    assert client.get("/v1/panchang", headers=other).status_code == 200


def test_install_limit_applies_alongside_the_address():
    client = _client(ai_limit=10, ai_install_limit=1)
    headers = {"X-Forwarded-For": "203.0.113.9", "X-Install-Id": "rl-install-1"}
    assert client.get("/v1/ai/status", headers=headers).status_code == 200
    assert client.get("/v1/ai/status", headers=headers).status_code == 429

    other = {**headers, "X-Install-Id": "rl-install-2"}
    assert client.get("/v1/ai/status", headers=other).status_code == 200


def test_unlisted_paths_are_not_limited():
    client = _client(compute_limit=1)
    for _ in range(3):
        assert client.get("/v1/health").status_code == 200


def test_middleware_can_be_disabled():
    client = _client(compute_limit=1, enabled=False)
    for _ in range(3):
        assert client.get("/v1/panchang").status_code == 200
