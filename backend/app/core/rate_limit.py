"""Request limits for a small multi-organization deployment: failed logins, and the routes that spend AI quota.

Counts live in this process's memory. ponytail: one server process; with several instances, move the counts to a shared
store (Redis or a MongoDB TTL collection) so every instance sees the same limits.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status

from app.api.deps import CurrentUser
from app.core.config import settings


class SlidingWindow:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _trim(self, key: str, window: float, now: float) -> deque[float]:
        hits = self._hits[key]
        while hits and hits[0] <= now - window:
            hits.popleft()
        return hits

    def retry_after(self, key: str, limit: int, window: float) -> int:
        """Seconds until the key may act again; 0 when it is under its limit."""
        now = time.monotonic()
        hits = self._trim(key, window, now)
        return 0 if len(hits) < limit else max(1, int(hits[0] + window - now) + 1)

    def hit(self, key: str) -> None:
        self._hits[key].append(time.monotonic())

    def clear(self, key: str | None = None) -> None:
        self._hits.pop(key, None) if key else self._hits.clear()


WINDOW = SlidingWindow()


def _too_many(seconds: int, message: str) -> HTTPException:
    return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=message, headers={"Retry-After": str(seconds)})


def check_login(request: Request, email: str) -> None:
    """Refuse a login while this e-mail has too many recent failures, or this address too many recent attempts."""
    window = settings.LOGIN_WINDOW_MINUTES * 60
    ip = request.client.host if request.client else "unknown"
    for key, limit in ((f"login-fail:{email.lower()}", settings.LOGIN_MAX_FAILURES),
                       (f"login-ip:{ip}", settings.LOGIN_MAX_ATTEMPTS_PER_IP)):
        wait = WINDOW.retry_after(key, limit, window)
        if wait:
            raise _too_many(wait, f"Too many sign-in attempts. Try again in {max(1, wait // 60)} minute(s).")
    WINDOW.hit(f"login-ip:{ip}")


def record_login_failure(email: str) -> None:
    WINDOW.hit(f"login-fail:{email.lower()}")


def record_login_success(email: str) -> None:
    WINDOW.clear(f"login-fail:{email.lower()}")


async def ai_request_allowed(context: CurrentUser) -> None:
    """Route dependency for anything that calls a model: per user per minute, per organization per hour."""
    checks = ((f"ai-user:{context.user_id}", settings.AI_USER_REQUESTS_PER_MINUTE, 60),
              (f"ai-org:{context.organization_id}", settings.AI_ORG_REQUESTS_PER_HOUR, 3600))
    for key, limit, window in checks:
        wait = WINDOW.retry_after(key, limit, window)
        if wait:
            raise _too_many(wait, f"The AI request limit was reached. Try again in {wait} second(s).")
    for key, _, _ in checks:
        WINDOW.hit(key)


AILimited = Depends(ai_request_allowed)
