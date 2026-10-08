"""Persist a LeagueSnapshot: idempotent upserts, one DB transaction per sync."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from fantasy_gm import credentials, demo
from fantasy_gm.config import Settings
from fantasy_gm.credentials import Cookies
from fantasy_gm.db import (
    League,
    Matchup,
    Player,
    PlayerPoints,
    ProGame,
    RosterEntry,
    SyncRun,
    Team,
    Transaction,
    session_scope,
    utcnow,
)
from fantasy_gm.domain import (
    LeagueSnapshot,
    LiveSnapshot,
    MatchupData,
    PlayerData,
    ProGameData,
    RosterSlotData,
)
from fantasy_gm.espn.adapter import EspnSource
from fantasy_gm.espn.client import EspnAuthError, EspnClient

log = logging.getLogger(__name__)

# Transactions can be re-processed/cancelled for a while; re-fetch this many recent weeks.
TRANSACTION_LOOKBACK_WEEKS = 2


def store_snapshot(session: Session, snap: LeagueSnapshot) -> League:
    league = session.scalar(
        select(League).where(
            League.platform == snap.platform,
            League.external_id == snap.external_id,
            League.season == snap.season,
        )
    )
    if league is None:
        league = League(platform=snap.platform, external_id=snap.external_id, season=snap.season)
        session.add(league)
    league.name = snap.name
    league.current_week = snap.current_week
    league.final_regular_week = snap.final_regular_week
    league.settings = snap.settings
    session.flush()

    # Teams
    teams = {
        t.external_id: t for t in session.scalars(select(Team).where(Team.league_id == league.id))
    }
    for td in snap.teams:
        team = teams.get(td.external_id)
        if team is None:
            team = teams[td.external_id] = Team(league_id=league.id, external_id=td.external_id)
            session.add(team)
        for attr in (
            "name",
            "abbrev",
            "owner_name",
            "owner_ids",
            "wins",
            "losses",
            "ties",
            "points_for",
            "points_against",
            "playoff_seed",
            "waiver_rank",
            "faab_spent",
            "logo_url",
        ):
            setattr(team, attr, getattr(td, attr))
    session.flush()
    team_ids = {ext: t.id for ext, t in teams.items()}
    league.my_team_id = team_ids.get(snap.my_team_external_id) if snap.my_team_external_id else None

    player_ids = _upsert_players(session, snap.platform, snap.players)
    _replace_rosters(
        session, league.id, {t.external_id: t.roster for t in snap.teams}, team_ids, player_ids
    )
    _upsert_points(session, league.id, snap.season, snap.players, player_ids)
    _upsert_matchups(session, league.id, snap.matchups, team_ids)
    _upsert_pro_games(session, snap.pro_games)

    # Transactions
    txns = {
        t.external_id: t
        for t in session.scalars(select(Transaction).where(Transaction.league_id == league.id))
    }
    for tdata in snap.transactions:
        t = txns.get(tdata.external_id)
        if t is None:
            t = txns[tdata.external_id] = Transaction(
                league_id=league.id, external_id=tdata.external_id
            )
            session.add(t)
        t.type, t.status = tdata.type, tdata.status
        t.team_id = team_ids.get(tdata.team_external_id) if tdata.team_external_id else None
        t.week, t.bid_amount = tdata.week, tdata.bid_amount
        t.proposed_at, t.processed_at = tdata.proposed_at, tdata.processed_at
        t.items = [
            {
                "type": i.type,
                "player_id": player_ids.get(i.player_external_id) if i.player_external_id else None,
                "player_external_id": i.player_external_id,
                "from_team_id": team_ids.get(i.from_team_external_id)
                if i.from_team_external_id
                else None,
                "to_team_id": team_ids.get(i.to_team_external_id)
                if i.to_team_external_id
                else None,
            }
            for i in tdata.items
        ]

    league.last_synced_at = league.live_updated_at = utcnow()
    return league


def store_live(session: Session, league: League, snap: LiveSnapshot) -> None:
    """Apply an in-game refresh: lineups, this week's points, scores and NFL game states."""
    team_ids = {
        t.external_id: t.id
        for t in session.scalars(select(Team).where(Team.league_id == league.id))
    }
    player_ids = _upsert_players(session, snap.platform, snap.players)
    _replace_rosters(session, league.id, snap.rosters, team_ids, player_ids)
    _upsert_points(session, league.id, snap.season, snap.players, player_ids)
    _upsert_matchups(session, league.id, snap.matchups, team_ids)
    _upsert_pro_games(session, snap.pro_games)
    league.live_updated_at = utcnow()


def _upsert_players(session: Session, platform: str, data: list[PlayerData]) -> dict[str, int]:
    """Players are global per platform. Returns external id -> Player.id."""
    ext_ids = [p.external_id for p in data]
    players: dict[str, Player] = {}
    for chunk in (ext_ids[i : i + 500] for i in range(0, len(ext_ids), 500)):
        players.update(
            (p.external_id, p)
            for p in session.scalars(
                select(Player).where(Player.platform == platform, Player.external_id.in_(chunk))
            )
        )
    now = utcnow()
    for pd in data:
        player = players.get(pd.external_id)
        if player is None:
            player = players[pd.external_id] = Player(platform=platform, external_id=pd.external_id)
            session.add(player)
        player.full_name = pd.full_name
        player.position = pd.position
        player.pro_team = pd.pro_team
        player.injury_status = pd.injury_status
        if pd.eligible_slots:
            player.eligible_slots = pd.eligible_slots
        if pd.percent_owned is not None:
            player.percent_owned = pd.percent_owned
            player.percent_owned_change = pd.percent_owned_change
        player.updated_at = now
    session.flush()
    return {ext: p.id for ext, p in players.items()}


def _replace_rosters(
    session: Session,
    league_id: int,
    rosters: dict[str, list[RosterSlotData]],
    team_ids: dict[str, int],
    player_ids: dict[str, int],
) -> None:
    """The roster table is a snapshot: replace it wholesale."""
    session.execute(delete(RosterEntry).where(RosterEntry.league_id == league_id))
    for team_ext, roster in rosters.items():
        team_id = team_ids.get(team_ext)
        if team_id is None:
            continue
        seen: set[str] = set()
        for slot in roster:
            pid = player_ids.get(slot.player_external_id)
            if pid is None or slot.player_external_id in seen:
                continue
            seen.add(slot.player_external_id)
            session.add(
                RosterEntry(
                    league_id=league_id,
                    team_id=team_id,
                    player_id=pid,
                    slot=slot.slot,
                    acquisition_type=slot.acquisition_type,
                )
            )


def _upsert_points(
    session: Session,
    league_id: int,
    season: int,
    data: list[PlayerData],
    player_ids: dict[str, int],
) -> None:
    """Player points accumulate across syncs; live refreshes overwrite the current week."""
    existing = {
        (pp.player_id, pp.week, pp.kind): pp
        for pp in session.scalars(
            select(PlayerPoints).where(
                PlayerPoints.league_id == league_id, PlayerPoints.season == season
            )
        )
    }
    for pd in data:
        pid = player_ids[pd.external_id]
        for (week, kind), value in pd.points.items():
            row = existing.get((pid, week, kind))
            if row is None:
                row = PlayerPoints(
                    league_id=league_id, player_id=pid, season=season, week=week, kind=kind
                )
                session.add(row)
                existing[(pid, week, kind)] = row
            row.points = value


def _upsert_matchups(
    session: Session, league_id: int, data: list[MatchupData], team_ids: dict[str, int]
) -> None:
    matchups = {
        m.external_id: m
        for m in session.scalars(select(Matchup).where(Matchup.league_id == league_id))
    }
    for md in data:
        home = team_ids.get(md.home_team_external_id)
        if home is None:
            continue
        m = matchups.get(md.external_id)
        if m is None:
            m = matchups[md.external_id] = Matchup(league_id=league_id, external_id=md.external_id)
            session.add(m)
        m.week = md.week
        m.home_team_id = home
        m.away_team_id = (
            team_ids.get(md.away_team_external_id) if md.away_team_external_id else None
        )
        m.home_points, m.away_points = md.home_points, md.away_points
        m.home_projected, m.away_projected = md.home_projected, md.away_projected
        m.home_win_prob, m.away_win_prob = md.home_win_prob, md.away_win_prob
        m.winner = md.winner
        m.is_playoff = md.is_playoff


def _upsert_pro_games(session: Session, data: list[ProGameData]) -> None:
    if not data:
        return
    games = {
        g.external_id: g
        for g in session.scalars(
            select(ProGame).where(ProGame.external_id.in_([d.external_id for d in data]))
        )
    }
    now = utcnow()
    for gd in data:
        g = games.get(gd.external_id)
        if g is None:
            g = games[gd.external_id] = ProGame(external_id=gd.external_id)
            session.add(g)
        g.season, g.week = gd.season, gd.week
        g.home_team, g.away_team = gd.home_team, gd.away_team
        g.home_score, g.away_score = gd.home_score, gd.away_score
        g.state, g.detail, g.kickoff = gd.state, gd.detail, gd.kickoff
        g.updated_at = now


# --- live refresh -------------------------------------------------------------

# Start refreshing this long before a kickoff, so lineups and inactives are current.
PREGAME_WINDOW = timedelta(minutes=90)


def games_active(games: list[ProGame], now: datetime | None = None) -> bool:
    """True while any game is in progress or about to start.

    A stored game that should have kicked off but still reads 'pre' counts as active:
    our copy is stale, and only a refresh will tell us it started.
    """
    now = now or utcnow()
    for g in games:
        if g.state == "in":
            return True
        if g.state == "pre" and g.kickoff is not None and g.kickoff - PREGAME_WINDOW <= now:
            return True
    return False


def needs_live_refresh(session: Session, league: League, now: datetime | None = None) -> bool:
    if not league.current_week:
        return False
    games = list(
        session.scalars(
            select(ProGame).where(
                ProGame.season == league.season, ProGame.week == league.current_week
            )
        )
    )
    if not games:
        return True  # never fetched this week's games: find out
    return games_active(games, now)


def refresh_live(
    league_id: int,
    settings: Settings,
    *,
    force: bool = False,
    candidates: list[Cookies | None] | None = None,
) -> bool:
    """Refresh a league's in-game data if games are on (or ``force``). Returns True if it ran."""
    with session_scope() as s:
        league = s.get(League, league_id)
        if league is None:
            raise ValueError(f"No league with id {league_id}")
        if league.platform != "espn" or not league.current_week:
            return False
        if not force and not needs_live_refresh(s, league):
            return False
        ext, season, week = league.external_id, league.season, league.current_week

    snap = with_cookies(
        candidates or credentials.for_league(league_id, settings),
        settings,
        lambda c: EspnSource(c).fetch_live(ext, season, week),
    )
    with session_scope() as s:
        league = s.get(League, league_id)
        if league is None:  # deleted mid-refresh
            return False
        store_live(s, league, snap)
    return True


def make_espn_client(settings: Settings, cookies: Cookies | None) -> EspnClient:
    if cookies is None:
        return EspnClient()
    return EspnClient(espn_s2=cookies.espn_s2, swid=cookies.swid)


def with_cookies[T](
    candidates: list[Cookies | None],
    settings: Settings,
    fn: Callable[[EspnClient], T],
    *,
    mark_failures: bool = True,
) -> T:
    """Run ``fn`` with each set of cookies until ESPN accepts one.

    Users' cookies that ESPN accepts are marked ok; refused ones are marked expired,
    unless ``mark_failures`` is off (a user trying a league they may not belong to).
    """
    error: EspnAuthError | None = None
    for cookies in candidates or [None]:
        try:
            with make_espn_client(settings, cookies) as client:
                result = fn(client)
        except EspnAuthError as e:
            error = e
            if mark_failures:
                credentials.mark(cookies, ok=False)
            continue
        credentials.mark(cookies, ok=True)
        return result
    assert error is not None
    raise error


def sync_league(
    league_id: int, settings: Settings, candidates: list[Cookies | None] | None = None
) -> SyncRun:
    """Sync one stored league from its platform, recording the run's outcome."""
    with session_scope() as s:
        league = s.get(League, league_id)
        if league is None:
            raise ValueError(f"No league with id {league_id}")
        platform, ext, season = league.platform, league.external_id, league.season
        has_txns = s.scalar(
            select(Transaction.id).where(Transaction.league_id == league_id).limit(1)
        )
        current_week = league.current_week
        run = SyncRun(league_id=league_id)
        s.add(run)
        s.flush()
        run_id = run.id

    if platform not in ("espn", demo.PLATFORM):
        raise ValueError(f"Unsupported platform {platform!r}")

    txn_weeks = None
    if has_txns and current_week:
        txn_weeks = range(max(1, current_week - TRANSACTION_LOOKBACK_WEEKS), current_week + 1)

    error: str | None = None
    try:
        if platform == demo.PLATFORM:
            snap = demo.build_snapshot()
        else:
            snap = with_cookies(
                candidates or credentials.for_league(league_id, settings),
                settings,
                lambda c: EspnSource(c).fetch_snapshot(ext, season, transaction_weeks=txn_weeks),
            )
        with session_scope() as s:
            store_snapshot(s, snap)
    except Exception as e:  # recorded on the run and re-raised for the caller
        error = f"{type(e).__name__}: {e}"
        log.exception("Sync failed for league %s", league_id)
        raise
    finally:
        with session_scope() as s:
            run = s.get(SyncRun, run_id)
            assert run is not None
            run.finished_at = utcnow()
            run.status = "error" if error else "ok"
            run.error = error[:2000] if error else None
            s.flush()
            s.expunge(run)
    return run


def add_espn_league(
    external_id: str,
    season: int,
    settings: Settings,
    candidates: list[Cookies | None] | None = None,
) -> int:
    """Fetch a league for the first time and store it. Returns the new League.id."""
    snap = with_cookies(
        candidates or [credentials.settings_cookies(settings)],
        settings,
        lambda c: EspnSource(c).fetch_snapshot(external_id, season),
        mark_failures=False,
    )
    with session_scope() as s:
        league = store_snapshot(s, snap)
        s.flush()
        return league.id


def ensure_demo_league() -> int:
    """Store (or refresh in place) the made-up demo league. Returns its League.id."""
    snap = demo.build_snapshot()
    with session_scope() as s:
        for old in s.scalars(
            select(League).where(League.platform == demo.PLATFORM, League.season != snap.season)
        ):
            s.delete(old)  # a pool from an older season
        league = store_snapshot(s, snap)
        s.flush()
        return league.id
