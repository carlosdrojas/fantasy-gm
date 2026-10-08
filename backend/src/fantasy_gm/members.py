"""League membership: which users can see a league, and which team is theirs in it.

A league is stored once however many users add it. Joining a league someone already
added still asks ESPN, with the joiner's own cookies, whether they can read it: knowing
a league id must not be enough to see a private league.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from fantasy_gm import credentials, demo
from fantasy_gm.config import Settings
from fantasy_gm.db import ChatMessage, League, LeagueMember, User, session_scope, utcnow
from fantasy_gm.espn.client import EspnClient
from fantasy_gm.sync import add_espn_league, with_cookies

# Don't write last_viewed_at on every page view.
VIEW_TOUCH_INTERVAL = timedelta(minutes=10)
# Leagues nobody has opened for this long stop syncing in the background.
ACTIVE_FOR = timedelta(days=7)


class LeagueLimitError(Exception):
    pass


class AlreadyMemberError(Exception):
    pass


def member(s: Session, user_id: int, league_id: int) -> LeagueMember | None:
    return s.scalar(
        select(LeagueMember).where(
            LeagueMember.user_id == user_id, LeagueMember.league_id == league_id
        )
    )


def join(user_id: int, external_id: str, season: int, settings: Settings) -> int:
    """Add an ESPN league to a user's account, fetching it if it's new. Returns League.id.

    Raises EspnAuthError if ESPN won't show this user the league, LeagueLimitError,
    AlreadyMemberError, and EspnError for other ESPN failures.
    """
    with session_scope() as s:
        count = s.scalar(select(func.count()).where(LeagueMember.user_id == user_id)) or 0
        if count >= settings.max_leagues_per_user:
            raise LeagueLimitError(
                f"You can add up to {settings.max_leagues_per_user} leagues. Remove one first."
            )
        existing = s.scalar(
            select(League.id).where(
                League.platform == "espn",
                League.external_id == external_id,
                League.season == season,
            )
        )
        if existing is not None and member(s, user_id, existing):
            raise AlreadyMemberError("You've already added this league.")

    cookies = credentials.for_user(user_id, settings)
    candidates = [cookies, None] if cookies else [None]
    if existing is None:
        league_id = add_espn_league(external_id, season, settings, candidates)
    else:
        league_id = existing

        def check(c: EspnClient) -> None:
            c.league(external_id, season, ["mSettings"])

        with_cookies(candidates, settings, check, mark_failures=False)

    team = credentials.team_for_swid(league_id, cookies.swid if cookies else None)
    with session_scope() as s:
        if member(s, user_id, league_id) is None:  # a double-submit may have won the race
            s.add(LeagueMember(user_id=user_id, league_id=league_id, my_team_id=team))
    return league_id


def leave(user_id: int, league_id: int) -> None:
    """Remove a league from a user's account; delete it once nobody has it."""
    with session_scope() as s:
        s.execute(
            delete(LeagueMember).where(
                LeagueMember.user_id == user_id, LeagueMember.league_id == league_id
            )
        )
        _delete_if_orphaned(s, league_id)


def _delete_if_orphaned(s: Session, league_id: int) -> None:
    s.flush()
    league = s.get(League, league_id)
    if league is None or league.platform == demo.PLATFORM:
        return
    if s.scalar(select(func.count()).where(LeagueMember.league_id == league_id)) == 0:
        s.delete(league)


def detect_teams(user_id: int, settings: Settings) -> None:
    """After a user saves cookies, find their team in leagues where it isn't set."""
    cookies = credentials.for_user(user_id, settings)
    if cookies is None:
        return
    with session_scope() as s:
        for m in s.scalars(
            select(LeagueMember).where(
                LeagueMember.user_id == user_id, LeagueMember.my_team_id.is_(None)
            )
        ):
            m.my_team_id = credentials.team_for_swid(m.league_id, cookies.swid)


def touch(s: Session, m: LeagueMember) -> None:
    now = utcnow()
    if m.last_viewed_at is None or now - m.last_viewed_at > VIEW_TOUCH_INTERVAL:
        m.last_viewed_at = now


def active_league_ids(s: Session) -> list[int]:
    """ESPN leagues someone opened recently: the ones worth syncing in the background."""
    since = utcnow() - ACTIVE_FOR
    return list(
        s.scalars(
            select(League.id)
            .join(LeagueMember, LeagueMember.league_id == League.id)
            .where(League.platform == "espn", LeagueMember.last_viewed_at >= since)
            .distinct()
        )
    )


def delete_user(user_id: int) -> None:
    """Delete an account: memberships, cookies and conversations go with it (cascade),
    and leagues nobody else has are deleted too."""
    with session_scope() as s:
        league_ids = list(
            s.scalars(select(LeagueMember.league_id).where(LeagueMember.user_id == user_id))
        )
        # Explicit, since databases from before accounts lack this foreign key.
        s.execute(delete(ChatMessage).where(ChatMessage.user_id == user_id))
        user = s.get(User, user_id)
        if user is not None:
            s.delete(user)
        s.flush()
        for lid in league_ids:
            _delete_if_orphaned(s, lid)
