"""Password hashing and JWT handling."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt
from passlib.context import CryptContext

from app.core.config import settings

# bcrypt has a hard 72-byte limit on the input password.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__truncate_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password[:72])


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain[:72], hashed)
    except Exception:
        return False


def create_access_token(subject: str, extra_claims: Optional[dict[str, Any]] = None) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Raises jwt.PyJWTError subclasses on invalid/expired tokens."""
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


OAUTH_STATE_TTL_MINUTES = 10


def create_oauth_state(
    *,
    organization_id: str,
    user_id: str,
    provider: str,
    ttl_minutes: int = OAUTH_STATE_TTL_MINUTES,
) -> str:
    """Signed, short-lived OAuth `state`.

    Binds a provider callback to the organization and user that started the
    flow, and doubles as CSRF protection: a callback carrying a state this
    server did not sign is rejected.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "type": "oauth_state",
        "provider": provider,
        "org": organization_id,
        "sub": user_id,
        "nonce": secrets.token_urlsafe(16),
        "iat": now,
        "exp": now + timedelta(minutes=ttl_minutes),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_oauth_state(state: str, *, provider: str) -> dict[str, Any]:
    """Return the state claims, or raise a jwt.PyJWTError subclass."""
    claims = jwt.decode(state, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    if claims.get("type") != "oauth_state" or claims.get("provider") != provider:
        raise jwt.InvalidTokenError("State was not issued for this provider.")
    return claims
