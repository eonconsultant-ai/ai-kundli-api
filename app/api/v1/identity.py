from __future__ import annotations

from fastapi import Request

_ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


def valid_install_id(raw: str | None) -> str | None:
    candidate = (raw or "").strip()
    if 8 <= len(candidate) <= 64 and all(char in _ALLOWED for char in candidate):
        return candidate
    return None


def install_id(raw: str | None, request: Request) -> str:
    return valid_install_id(raw) or f"ip:{request.client.host if request.client else 'unknown'}"
