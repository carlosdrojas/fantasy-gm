"""Encryption for secrets stored in the database (users' ESPN cookies).

Fernet (AES-128-CBC + HMAC-SHA256) keyed from ``FGM_SECRET_KEY``. Any long random
string works as the secret; it is stretched into a Fernet key with SHA-256. Losing or
changing the secret makes stored cookies unreadable: users just paste them again.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

MIN_SECRET_LENGTH = 32


class SecretsUnavailableError(RuntimeError):
    """No (or too short a) FGM_SECRET_KEY, so secrets can't be stored or read."""


def _fernet(secret: str | None) -> Fernet:
    if not secret or len(secret) < MIN_SECRET_LENGTH:
        raise SecretsUnavailableError(
            f"Set FGM_SECRET_KEY (at least {MIN_SECRET_LENGTH} random characters) to store "
            "ESPN cookies."
        )
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt(secret: str | None, value: str) -> str:
    return _fernet(secret).encrypt(value.encode()).decode()


def decrypt(secret: str | None, token: str) -> str | None:
    """The plaintext, or None if the token was made with a different secret."""
    try:
        return _fernet(secret).decrypt(token.encode()).decode()
    except InvalidToken:
        return None
