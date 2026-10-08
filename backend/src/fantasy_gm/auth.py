"""Who is making a request: a signed-in user (Clerk session token), the single local
user of an install without accounts, or an anonymous demo visitor.

The frontend forwards the Clerk session token as ``Authorization: Bearer <jwt>``. We
verify it against the instance's published keys (JWKS); no Clerk SDK or API calls.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

import jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from fantasy_gm.config import Settings
from fantasy_gm.db import User, session_scope

log = logging.getLogger(__name__)

LOCAL_USER = "local"


class AuthError(Exception):
    """The token is missing a required part, expired, or not from our issuer."""


@dataclass(frozen=True)
class Viewer:
    user_id: int | None  # User.id; None for anonymous visitors

    @property
    def anonymous(self) -> bool:
        return self.user_id is None


ANONYMOUS = Viewer(None)


@lru_cache(maxsize=4)
def _jwks_client(issuer: str) -> jwt.PyJWKClient:
    # Caches keys and refetches on an unknown key id (Clerk key rotation).
    return jwt.PyJWKClient(f"{issuer.rstrip('/')}/.well-known/jwks.json", lifespan=3600)


def verify_token(token: str, settings: Settings) -> str:
    """Return the token's subject (the Clerk user id), or raise AuthError."""
    issuer = settings.auth_issuer
    if not issuer:
        raise AuthError("Accounts are not enabled on this server.")
    try:
        key = _jwks_client(issuer).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            issuer=issuer.rstrip("/"),
            options={"require": ["exp", "iat", "sub", "iss"]},
            leeway=10,
        )
    except jwt.PyJWTError as e:
        raise AuthError(f"Invalid session token: {e}") from e
    azp = claims.get("azp")
    allowed = settings.auth_authorized_parties
    if allowed and azp not in allowed:
        raise AuthError("Session token was issued for another site.")
    return str(claims["sub"])


def user_id_for(external_id: str) -> int:
    """The User.id for an auth subject, creating the row on first sight."""
    with session_scope() as s:
        uid = s.scalar(select(User.id).where(User.external_id == external_id))
        if uid is not None:
            return uid
    try:
        with session_scope() as s:
            user = User(external_id=external_id)
            s.add(user)
            s.flush()
            return user.id
    except IntegrityError:  # created concurrently by another request
        with session_scope() as s:
            uid = s.scalar(select(User.id).where(User.external_id == external_id))
            assert uid is not None
            return uid


def viewer_from_header(authorization: str | None, settings: Settings) -> Viewer:
    """Resolve the request's viewer. Without accounts, everyone is the local user."""
    if not settings.accounts_enabled:
        return Viewer(user_id_for(LOCAL_USER))
    if not authorization:
        return ANONYMOUS
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthError("Expected 'Authorization: Bearer <token>'.")
    return Viewer(user_id_for(verify_token(token.strip(), settings)))
