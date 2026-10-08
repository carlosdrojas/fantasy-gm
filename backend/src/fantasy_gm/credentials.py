"""ESPN cookies: the install's own (from .env) or each user's (encrypted in the database).

A sync tries the cookies of a league's members in turn, so a private league keeps
syncing as long as any member's cookies are valid. ESPN refusing a set marks it
expired, and its owner is asked for fresh ones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import delete, select

from fantasy_gm import crypto
from fantasy_gm.config import Settings
from fantasy_gm.db import EspnCredential, LeagueMember, Team, session_scope, utcnow

SWID_RE = re.compile(
    r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$"
)


@dataclass(frozen=True)
class Cookies:
    espn_s2: str
    swid: str
    credential_id: int | None = None  # EspnCredential.id; None for the .env cookies

    def __repr__(self) -> str:  # never print the cookie values
        return f"Cookies(credential_id={self.credential_id})"


def _secret(settings: Settings) -> str | None:
    return settings.secret_key.get_secret_value() if settings.secret_key else None


def settings_cookies(settings: Settings) -> Cookies | None:
    if settings.espn_s2 and settings.espn_swid:
        return Cookies(settings.espn_s2.get_secret_value(), settings.espn_swid)
    return None


def normalize_swid(swid: str) -> str:
    swid = swid.strip()
    if not swid.startswith("{"):
        swid = "{" + swid + "}"
    return swid.upper()


def save(user_id: int, espn_s2: str, swid: str, settings: Settings) -> None:
    """Store (or replace) a user's cookies. Raises ValueError on a malformed SWID."""
    swid = normalize_swid(swid)
    espn_s2 = espn_s2.strip()
    if not SWID_RE.match(swid):
        raise ValueError("SWID should look like {XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}.")
    if len(espn_s2) < 50:
        raise ValueError("That espn_s2 value looks too short. Copy the whole cookie value.")
    secret = _secret(settings)
    s2_enc, swid_enc = crypto.encrypt(secret, espn_s2), crypto.encrypt(secret, swid)
    with session_scope() as s:
        cred = s.scalar(select(EspnCredential).where(EspnCredential.user_id == user_id))
        if cred is None:
            cred = EspnCredential(user_id=user_id)
            s.add(cred)
        cred.espn_s2_encrypted, cred.swid_encrypted = s2_enc, swid_enc
        cred.status, cred.updated_at, cred.checked_at = "unverified", utcnow(), None


def remove(user_id: int) -> None:
    with session_scope() as s:
        s.execute(delete(EspnCredential).where(EspnCredential.user_id == user_id))


def status(user_id: int) -> dict | None:
    with session_scope() as s:
        cred = s.scalar(select(EspnCredential).where(EspnCredential.user_id == user_id))
        if cred is None:
            return None
        return {"status": cred.status, "updated_at": cred.updated_at, "checked_at": cred.checked_at}


def for_user(user_id: int, settings: Settings) -> Cookies | None:
    """A user's cookies, or None if they have none (or they can't be decrypted)."""
    with session_scope() as s:
        cred = s.scalar(select(EspnCredential).where(EspnCredential.user_id == user_id))
        if cred is None:
            return None
        return _decrypt(cred, settings)


def _decrypt(cred: EspnCredential, settings: Settings) -> Cookies | None:
    secret = _secret(settings)
    try:
        s2 = crypto.decrypt(secret, cred.espn_s2_encrypted)
        swid = crypto.decrypt(secret, cred.swid_encrypted)
    except crypto.SecretsUnavailableError:
        return None
    return Cookies(s2, swid, cred.id) if s2 and swid else None


def for_league(league_id: int, settings: Settings) -> list[Cookies | None]:
    """Cookies to try when syncing a league, best first; ``None`` means no cookies
    (enough for a public league)."""
    if not settings.accounts_enabled:
        return [settings_cookies(settings)]
    with session_scope() as s:
        creds = list(
            s.scalars(
                select(EspnCredential)
                .join(LeagueMember, LeagueMember.user_id == EspnCredential.user_id)
                .where(LeagueMember.league_id == league_id, EspnCredential.status != "expired")
                .order_by(EspnCredential.status == "ok", EspnCredential.updated_at)
            )
        )
        cookies = [c for cred in reversed(creds) if (c := _decrypt(cred, settings))]
    return [*cookies, None]


def mark(cookies: Cookies | None, ok: bool) -> None:
    """Record whether ESPN accepted a user's cookies."""
    if cookies is None or cookies.credential_id is None:
        return
    with session_scope() as s:
        cred = s.get(EspnCredential, cookies.credential_id)
        if cred is not None:
            cred.status, cred.checked_at = ("ok" if ok else "expired"), utcnow()


def team_for_swid(league_id: int, swid: str | None) -> int | None:
    """The Team.id in a league owned by this SWID."""
    if not swid:
        return None
    swid = swid.lower()
    with session_scope() as s:
        for team in s.scalars(select(Team).where(Team.league_id == league_id)):
            if swid in [str(o).lower() for o in team.owner_ids or []]:
                return team.id
    return None
