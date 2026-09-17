"""Encryption for secrets stored at rest (OAuth refresh tokens)."""
from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class TokenDecryptionError(Exception):
    """Stored ciphertext could not be decrypted with the current key."""


@lru_cache
def _fernet() -> Fernet:
    key = settings.TOKEN_ENCRYPTION_KEY.strip()
    if not key:
        # Derived fallback so a fresh install works; set TOKEN_ENCRYPTION_KEY in
        # production so rotating the JWT secret doesn't orphan stored tokens.
        digest = hashlib.sha256(settings.JWT_SECRET_KEY.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest).decode("ascii")
    return Fernet(key.encode("ascii"))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise TokenDecryptionError(
            "A stored credential could not be decrypted; reconnect the account."
        ) from exc
