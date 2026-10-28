"""Coarse request throttling.

Cloud Run runs several instances of this app, so the counters live in memory
and are enforced per instance rather than globally: they exist to stop one
client from looping the free endpoints, not to meter anybody exactly. AI spend
is still capped by the per-install daily quotas in the usage store.
"""

import time
from collections import deque

from starlette.types import ASGIApp, Receive, Scope, Send

WINDOW_SECONDS = 60.0
COMPUTE_SEGMENTS = frozenset({"panchang", "kundli", "matching", "search"})


class SlidingWindow:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._hits: dict[str, deque[float]] = {}

    def retry_after(self, key: str, now: float) -> int | None:
        """Record one hit for `key`; None means allowed, else seconds to wait."""
        hits = self._hits.setdefault(key, deque())
        cutoff = now - WINDOW_SECONDS
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) < self.limit:
            hits.append(now)
            return None
        return max(1, int(WINDOW_SECONDS - (now - hits[0])) + 1)

    def sweep(self, now: float) -> None:
        cutoff = now - WINDOW_SECONDS
        stale = [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for key in stale:
            del self._hits[key]


class RateLimitMiddleware:
    """Applies a sliding window to the endpoints that cost CPU or AI tokens."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        prefix: str = "/v1",
        enabled: bool = True,
        compute_limit: int = 120,
        ai_limit: int = 30,
        ai_install_limit: int = 15,
        events_limit: int = 60,
    ) -> None:
        self.app = app
        self.prefix = prefix.rstrip("/")
        self.enabled = enabled
        self._compute = SlidingWindow(compute_limit)
        self._ai = SlidingWindow(ai_limit)
        self._ai_install = SlidingWindow(ai_install_limit)
        self._events = SlidingWindow(events_limit)
        self._last_sweep = 0.0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.enabled or scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limits = self._limits(scope)
        if not limits:
            await self.app(scope, receive, send)
            return

        now = time.monotonic()
        if now - self._last_sweep > 300:
            self._last_sweep = now
            for window in (self._compute, self._ai, self._ai_install, self._events):
                window.sweep(now)

        for window, key in limits:
            retry_after = window.retry_after(key, now)
            if retry_after is not None:
                await self._reject(send, retry_after)
                return

        await self.app(scope, receive, send)

    def _limits(self, scope: Scope) -> list[tuple[SlidingWindow, str]]:
        path = scope.get("path", "")
        headers = {name.lower(): value for name, value in scope.get("headers") or []}

        if path == f"{self.prefix}/events" or path.startswith(f"{self.prefix}/events/"):
            window = self._events
        elif path.startswith(f"{self.prefix}/ai/"):
            window = self._ai
        elif self._is_compute(path):
            window = self._compute
        else:
            return []

        address = _client_address(scope, headers)
        if address is None:
            # Without a trustworthy address there is nothing to key on; serving
            # the request is better than throttling everybody under one key.
            return []

        limits = [(window, f"ip:{address}")]
        if window is self._ai:
            install = headers.get(b"x-install-id")
            if install:
                limits.append((self._ai_install, f"install:{install.decode('latin-1')[:64]}"))
        return limits

    def _is_compute(self, path: str) -> bool:
        head = f"{self.prefix}/"
        if not path.startswith(head):
            return False
        segment = path[len(head) :].split("/", 1)[0]
        return segment in COMPUTE_SEGMENTS

    async def _reject(self, send: Send, retry_after: int) -> None:
        body = b'{"detail":"Too many requests. Please try again shortly.","code":"rate_limited"}'
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"retry-after", str(retry_after).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def _client_address(scope: Scope, headers: dict[bytes, bytes]) -> str | None:
    # Cloud Run appends the peer address it saw, so the last entry is the one a
    # client cannot choose even if it sends an X-Forwarded-For of its own.
    forwarded = headers.get(b"x-forwarded-for")
    if forwarded:
        parts = [part.strip() for part in forwarded.decode("latin-1").split(",") if part.strip()]
        if parts:
            return parts[-1]
    client = scope.get("client")
    return client[0] if client else None
