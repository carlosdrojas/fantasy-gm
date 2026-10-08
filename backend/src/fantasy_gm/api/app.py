"""FastAPI app: read endpoints for the dashboard plus league add/sync."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import date

import anthropic
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from fantasy_gm import chat, demo, quick_answers
from fantasy_gm.analytics.league import (
    LeagueData,
    lineup_status,
    load_league,
    player_json,
    positional_strength,
    power_rankings,
    waiver_suggestions,
)
from fantasy_gm.analytics.lineup import optimal_lineup
from fantasy_gm.analytics.simulate import simulate, simulation_meta
from fantasy_gm.analytics.trades import evaluate_trade, find_trades, team_value
from fantasy_gm.config import Settings, get_settings
from fantasy_gm.db import (
    League,
    Player,
    ProGame,
    SyncRun,
    Team,
    Transaction,
    init_db,
    session_scope,
    utcnow,
)
from fantasy_gm.espn.client import EspnAuthError, EspnError, EspnNotFoundError
from fantasy_gm.sync import (
    add_espn_league,
    ensure_demo_league,
    games_active,
    refresh_live,
    sync_league,
)

log = logging.getLogger(__name__)

_sync_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(league_id: int) -> threading.Lock:
    with _locks_guard:
        return _sync_locks.setdefault(league_id, threading.Lock())


class AddLeague(BaseModel):
    league_id: str = Field(pattern=r"^\d+$")
    season: int = Field(default_factory=lambda: date.today().year, ge=2018, le=2100)


class TradeQuery(BaseModel):
    partner_team_id: int
    give: list[int] = Field(min_length=1, max_length=5)
    get: list[int] = Field(min_length=1, max_length=5)
    team_id: int | None = None


class QuickQuestion(BaseModel):
    question: str = Field(max_length=32)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(None, pattern=r"^[0-9a-f-]{8,64}$")


# Simulations and trade searches are pure functions of synced data: memoize per sync.
_memo: dict[tuple, object] = {}
_memo_guard = threading.Lock()
MEMO_MAX = 64


def memoized(key: tuple, fn):
    with _memo_guard:
        if key in _memo:
            return _memo[key]
    value = fn()
    with _memo_guard:
        if len(_memo) >= MEMO_MAX:
            _memo.pop(next(iter(_memo)))
        _memo[key] = value
    return value


def _sync_key(data: LeagueData) -> tuple:
    return (data.league.id, data.league.last_synced_at)


def _espn_league_ids() -> list[int]:
    with session_scope() as s:
        return list(s.scalars(select(League.id).where(League.platform == "espn")))


def sync_all(settings: Settings) -> None:
    ids = _espn_league_ids()
    for lid in ids:
        lock = _lock_for(lid)
        if not lock.acquire(blocking=False):
            continue
        try:
            sync_league(lid, settings)
        except Exception:  # already logged + recorded on the SyncRun
            pass
        finally:
            lock.release()


def live_all(settings: Settings) -> None:
    """Scheduler tick: refresh in-game data for every league whose games are on."""
    ids = _espn_league_ids()
    for lid in ids:
        lock = _lock_for(lid)
        if not lock.acquire(blocking=False):
            continue  # a full sync is running; it refreshes live data too
        try:
            refresh_live(lid, settings)
        except Exception:
            log.warning("Live refresh failed for league %s", lid, exc_info=True)
        finally:
            lock.release()


def create_app(settings: Settings | None = None, *, start_scheduler: bool = True) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        init_db(settings.database_url)
        if settings.demo_mode:
            ensure_demo_league()
        scheduler = None
        if (
            start_scheduler
            and not settings.demo_mode
            and (settings.sync_interval_minutes > 0 or settings.live_interval_seconds > 0)
        ):
            scheduler = BackgroundScheduler()
            if settings.sync_interval_minutes > 0:
                scheduler.add_job(
                    sync_all,
                    "interval",
                    minutes=settings.sync_interval_minutes,
                    args=[settings],
                    max_instances=1,
                    coalesce=True,
                )
            if settings.live_interval_seconds > 0:
                scheduler.add_job(
                    live_all,
                    "interval",
                    seconds=settings.live_interval_seconds,
                    args=[settings],
                    max_instances=1,
                    coalesce=True,
                    next_run_time=utcnow(),  # catch up right away on startup
                )
            scheduler.start()
        yield
        if scheduler:
            scheduler.shutdown(wait=False)

    app = FastAPI(title="Fantasy GM", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def db():
        with session_scope() as s:
            yield s

    def visible_leagues():
        """In demo mode only the demo league exists, whatever else is in the database."""
        q = select(League)
        return q.where(League.platform == demo.PLATFORM) if settings.demo_mode else q

    def visible_league(league_id: int, s: Session = Depends(db)) -> League:
        league = s.scalar(visible_leagues().where(League.id == league_id))
        if league is None:
            raise HTTPException(404, "League not found")
        return league

    def league_data(
        league: League = Depends(visible_league), s: Session = Depends(db)
    ) -> LeagueData:
        data = load_league(s, league.id)
        assert data is not None
        return data

    def not_demo() -> None:
        if settings.demo_mode:
            raise HTTPException(
                403, "This is a read-only demo. Run Fantasy GM yourself to do this."
            )

    def espn_http_error(e: EspnError) -> HTTPException:
        if isinstance(e, EspnAuthError):
            return HTTPException(401, str(e))
        if isinstance(e, EspnNotFoundError):
            return HTTPException(404, str(e))
        return HTTPException(502, str(e))

    # --- leagues ---------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict:
        return {
            "ok": True,
            "demo_mode": settings.demo_mode,
            # Claude chat in demo mode runs only on a key the visitor brings.
            "assistant_needs_user_key": settings.demo_mode,
            "espn_auth_configured": bool(settings.espn_s2 and settings.espn_swid),
        }

    @app.get("/api/leagues")
    def list_leagues(s: Session = Depends(db)) -> list[dict]:
        out = []
        for lg in s.scalars(visible_leagues().order_by(League.season.desc(), League.name)):
            my = s.get(Team, lg.my_team_id) if lg.my_team_id else None
            out.append(league_json(lg) | {"my_team": team_json(my) if my else None})
        return out

    @app.post("/api/leagues", status_code=201, dependencies=[Depends(not_demo)])
    def add_league(body: AddLeague, s: Session = Depends(db)) -> dict:
        existing = s.scalar(
            select(League).where(
                League.platform == "espn",
                League.external_id == body.league_id,
                League.season == body.season,
            )
        )
        if existing:
            raise HTTPException(409, "League already added")
        try:
            new_id = add_espn_league(body.league_id, body.season, settings)
        except EspnError as e:
            raise espn_http_error(e) from e
        return {"id": new_id}

    @app.delete("/api/leagues/{league_id}", status_code=204, dependencies=[Depends(not_demo)])
    def delete_league(league_id: int, s: Session = Depends(db)) -> None:
        league = s.get(League, league_id)
        if league is None:
            raise HTTPException(404, "League not found")
        s.delete(league)

    @app.post("/api/leagues/{league_id}/sync", dependencies=[Depends(not_demo)])
    def sync(league_id: int) -> dict:
        lock = _lock_for(league_id)
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "A sync is already running for this league")
        try:
            run = sync_league(league_id, settings)
        except ValueError as e:
            raise HTTPException(404, str(e)) from e
        except EspnError as e:
            raise espn_http_error(e) from e
        finally:
            lock.release()
        return {"status": run.status, "finished_at": run.finished_at}

    @app.get("/api/leagues/{league_id}")
    def league_overview(data: LeagueData = Depends(league_data), s: Session = Depends(db)) -> dict:
        lg = data.league
        last_run = s.scalar(
            select(SyncRun).where(SyncRun.league_id == lg.id).order_by(SyncRun.id.desc()).limit(1)
        )
        standings = sorted(
            data.teams.values(),
            key=lambda t: (t.playoff_seed or 99, -(t.wins + 0.5 * t.ties), -t.points_for),
        )
        week_matchups = [m for m in data.matchups if m.week == lg.current_week]
        status = {tid: lineup_status(rows) for tid, rows in data.rosters.items()}
        return league_json(lg) | {
            "teams": [team_json(t) for t in standings],
            "current_matchups": [
                matchup_json(m)
                | {
                    "home_lineup": status.get(m.home_team_id),
                    "away_lineup": status.get(m.away_team_id) if m.away_team_id else None,
                }
                for m in week_matchups
            ],
            "live": live_json(lg, data.pro_games),
            "last_sync": {
                "status": last_run.status,
                "started_at": last_run.started_at,
                "finished_at": last_run.finished_at,
                "error": last_run.error,
            }
            if last_run
            else None,
        }

    @app.get("/api/leagues/{league_id}/power")
    def power(data: LeagueData = Depends(league_data)) -> list[dict]:
        return power_rankings(data)

    @app.get("/api/leagues/{league_id}/positions")
    def positions(data: LeagueData = Depends(league_data)) -> dict:
        return {"teams": {str(k): v for k, v in positional_strength(data).items()}}

    @app.get("/api/leagues/{league_id}/teams/{team_id}")
    def team_detail(team_id: int, data: LeagueData = Depends(league_data)) -> dict:
        team = data.teams.get(team_id)
        if team is None:
            raise HTTPException(404, "Team not found in this league")
        rows = data.rosters.get(team_id, [])
        lineup = optimal_lineup([r.lineup_player(this_week=True) for r in rows], data.slot_counts)
        by_id = {r.player.id: r for r in rows}
        optimal = {slot: [by_id[p.player_id].player.id for p in ps] for slot, ps in lineup.items()}
        optimal_ids = {pid for ids in optimal.values() for pid in ids}
        current_starters = {r.player.id for r in rows if r.slot not in ("BE", "IR")}
        return {
            "team": team_json(team),
            "roster": [player_json(r) for r in sorted(rows, key=_slot_order)],
            "optimal_lineup": optimal,
            "lineup_changes": {
                "start": sorted(optimal_ids - current_starters),
                "sit": sorted(current_starters - optimal_ids),
            },
            "positions": positional_strength(data)[team_id],
        }

    @app.get("/api/leagues/{league_id}/matchups")
    def matchups(week: int | None = None, data: LeagueData = Depends(league_data)) -> list[dict]:
        return [matchup_json(m) for m in data.matchups if week is None or m.week == week]

    @app.get("/api/leagues/{league_id}/transactions")
    def transactions(
        limit: int = 100, league: League = Depends(visible_league), s: Session = Depends(db)
    ) -> list[dict]:
        txns = list(
            s.scalars(
                select(Transaction)
                .where(Transaction.league_id == league.id)
                .order_by(Transaction.proposed_at.desc().nullslast())
                .limit(min(limit, 500))
            )
        )
        pids = {i.get("player_id") for t in txns for i in t.items if i.get("player_id")}
        names = (
            {
                p.id: {"name": p.full_name, "position": p.position}
                for p in s.scalars(select(Player).where(Player.id.in_(pids)))
            }
            if pids
            else {}
        )
        return [
            {
                "id": t.id,
                "type": t.type,
                "status": t.status,
                "team_id": t.team_id,
                "week": t.week,
                "bid_amount": t.bid_amount,
                "proposed_at": t.proposed_at,
                "processed_at": t.processed_at,
                "items": [i | {"player": names.get(i.get("player_id"))} for i in t.items],
            }
            for t in txns
        ]

    @app.get("/api/leagues/{league_id}/waivers")
    def waivers(
        team_id: int | None = None, limit: int = 25, data: LeagueData = Depends(league_data)
    ) -> dict:
        tid = resolve_team(data, team_id)
        return {"team_id": tid, "suggestions": waiver_suggestions(data, tid, limit=min(limit, 100))}

    def resolve_team(data: LeagueData, team_id: int | None) -> int:
        tid = team_id or data.league.my_team_id
        if tid is None or tid not in data.teams:
            raise HTTPException(
                400, "Pass team_id, or set ESPN cookies so your team can be detected"
            )
        return tid

    @app.get("/api/leagues/{league_id}/odds")
    def odds(data: LeagueData = Depends(league_data)) -> dict:
        result = memoized(("odds", *_sync_key(data)), lambda: simulate(data))
        return {"teams": {str(k): v for k, v in result.items()}, **simulation_meta(data)}

    @app.get("/api/leagues/{league_id}/trades")
    def trades(
        team_id: int | None = None,
        partner_id: int | None = None,
        sort: str = "balanced",
        limit: int = 25,
        tradeable_now: bool = False,
        data: LeagueData = Depends(league_data),
    ) -> dict:
        if sort not in ("balanced", "gain", "likely"):
            raise HTTPException(422, "sort must be balanced, gain or likely")
        tid = resolve_team(data, team_id)
        if partner_id is not None and (partner_id not in data.teams or partner_id == tid):
            raise HTTPException(404, "Partner team not found")
        # Locks change as games kick off, so key on the live refresh time too.
        key = ("trades", *_sync_key(data), data.league.live_updated_at, tid, partner_id, sort)
        result = memoized(
            (*key, tradeable_now),
            lambda: find_trades(
                data,
                tid,
                partner_id,
                limit=100,
                sort=sort,  # type: ignore[arg-type]
                tradeable_now=tradeable_now,
            ),
        )
        return {"team_id": tid, "trades": result[: min(limit, 100)]}  # type: ignore[index]

    @app.post("/api/leagues/{league_id}/trades/analyze")
    def analyze_trade(body: TradeQuery, data: LeagueData = Depends(league_data)) -> dict:
        tid = resolve_team(data, body.team_id)
        if body.partner_team_id not in data.teams or body.partner_team_id == tid:
            raise HTTPException(404, "Partner team not found")
        try:
            result = evaluate_trade(data, tid, body.partner_team_id, body.give, body.get)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

        # Playoff odds before/after: re-simulate with both teams' post-trade strength.
        slots = data.slot_counts
        give, get = set(body.give), set(body.get)
        mine = data.rosters[tid]
        theirs = data.rosters[body.partner_team_id]
        my_new = [r for r in mine if r.player.id not in give] + [
            r for r in theirs if r.player.id in get
        ]
        their_new = [r for r in theirs if r.player.id not in get] + [
            r for r in mine if r.player.id in give
        ]
        override = {
            tid: team_value(my_new, slots, 10**6).lineup,
            body.partner_team_id: team_value(their_new, slots, 10**6).lineup,
        }
        before = memoized(("odds", *_sync_key(data)), lambda: simulate(data))
        after = simulate(data, strength_override=override)
        result["odds"] = {
            str(t): {"before": before[t], "after": after[t]}  # type: ignore[index]
            for t in (tid, body.partner_team_id)
        }
        return result

    @app.get("/api/assistant/questions")
    def quick_questions() -> list[dict]:
        return [{"id": q.id, "label": q.label} for q in quick_answers.QUESTIONS]

    @app.post("/api/leagues/{league_id}/assistant/quick")
    def quick_answer(body: QuickQuestion, data: LeagueData = Depends(league_data)) -> dict:
        q = quick_answers.QUESTIONS_BY_ID.get(body.question)
        if q is None:
            raise HTTPException(404, "Unknown question")
        try:
            text = quick_answers.answer(
                data,
                q.id,
                odds=lambda: memoized(("odds", *_sync_key(data)), lambda: simulate(data)),
            )
        except quick_answers.NoTeamError as e:
            raise HTTPException(400, str(e)) from e
        return {"question": q.id, "label": q.label, "answer": text, "source": "rules"}

    def anthropic_client(user_key: str | None) -> anthropic.Anthropic:
        """The visitor's own key if they sent one. Otherwise the server's, except in demo
        mode, where strangers must never spend it."""
        if user_key:
            return anthropic.Anthropic(api_key=user_key)
        if settings.demo_mode:
            raise HTTPException(
                401, "This demo's Claude chat needs your own Anthropic API key (add it above)."
            )
        key = settings.anthropic_api_key
        try:
            return (
                anthropic.Anthropic(api_key=key.get_secret_value())
                if key
                else anthropic.Anthropic()
            )
        except anthropic.AnthropicError as e:
            raise HTTPException(
                400, "No Anthropic API key. Set ANTHROPIC_API_KEY in backend/.env and restart."
            ) from e

    @app.post("/api/leagues/{league_id}/chat")
    def chat_turn(
        body: ChatRequest,
        league: League = Depends(visible_league),
        x_anthropic_key: str | None = Header(None, max_length=256),
    ) -> StreamingResponse:
        league_id = league.id
        conversation_id = body.conversation_id or str(uuid.uuid4())
        client = anthropic_client(x_anthropic_key.strip() if x_anthropic_key else None)

        def events():
            yield _sse({"type": "start", "conversation_id": conversation_id})
            try:
                for event in chat.run_chat(client, league_id, conversation_id, body.message):
                    yield _sse(event)
            except Exception:
                log.exception("Chat turn failed")
                yield _sse({"type": "error", "message": "Something went wrong on the server."})
                yield _sse({"type": "done"})

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/leagues/{league_id}/chat/{conversation_id}")
    def chat_history(conversation_id: str, _: League = Depends(visible_league)) -> list[dict]:
        return chat.transcript(conversation_id)

    @app.get("/api/leagues/{league_id}/free-agents")
    def free_agents(
        position: str | None = None, limit: int = 50, data: LeagueData = Depends(league_data)
    ) -> list[dict]:
        rows = [r for r in data.free_agents if position is None or r.player.position == position]
        rows.sort(key=lambda r: r.value.per_game, reverse=True)
        return [player_json(r) for r in rows[: min(limit, 250)]]

    @app.exception_handler(EspnError)
    async def _espn_error(_, exc: EspnError):
        e = espn_http_error(exc)
        return JSONResponse({"detail": e.detail}, status_code=e.status_code)

    return app


SLOT_ORDER = [
    "QB",
    "RB",
    "RB/WR",
    "WR",
    "WR/TE",
    "TE",
    "FLEX",
    "RB/WR/TE",
    "OP",
    "D/ST",
    "K",
    "BE",
    "IR",
]


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


def _slot_order(r) -> tuple[int, float]:
    idx = SLOT_ORDER.index(r.slot) if r.slot in SLOT_ORDER else len(SLOT_ORDER) - 2
    return idx, -r.value.per_game


def league_json(lg: League) -> dict:
    return {
        "id": lg.id,
        "platform": lg.platform,
        "external_id": lg.external_id,
        "season": lg.season,
        "name": lg.name,
        "current_week": lg.current_week,
        "final_regular_week": lg.final_regular_week,
        "my_team_id": lg.my_team_id,
        "settings": lg.settings,
        "last_synced_at": lg.last_synced_at,
        "live_updated_at": lg.live_updated_at,
    }


def live_json(lg: League, games: list[ProGame]) -> dict:
    """Game-day status: which NFL games are on, so the dashboard knows to auto-refresh."""
    return {
        "updated_at": lg.live_updated_at,
        "active": games_active(games),
        "games": [
            {
                "home_team": g.home_team,
                "away_team": g.away_team,
                "home_score": g.home_score,
                "away_score": g.away_score,
                "state": g.state,
                "detail": g.detail,
                "kickoff": g.kickoff,
            }
            for g in sorted(games, key=lambda g: (g.kickoff is None, g.kickoff, g.home_team))
        ],
    }


def team_json(t: Team) -> dict:
    return {
        "id": t.id,
        "external_id": t.external_id,
        "name": t.name,
        "abbrev": t.abbrev,
        "owner_name": t.owner_name,
        "logo_url": t.logo_url,
        "wins": t.wins,
        "losses": t.losses,
        "ties": t.ties,
        "points_for": round(t.points_for, 2),
        "points_against": round(t.points_against, 2),
        "playoff_seed": t.playoff_seed,
        "waiver_rank": t.waiver_rank,
        "faab_spent": t.faab_spent,
    }


def matchup_json(m) -> dict:
    return {
        "id": m.id,
        "week": m.week,
        "home_team_id": m.home_team_id,
        "away_team_id": m.away_team_id,
        "home_points": m.home_points,
        "away_points": m.away_points,
        "home_projected": m.home_projected,
        "away_projected": m.away_projected,
        "winner": m.winner,
        "is_playoff": m.is_playoff,
        "home_win_prob": m.home_win_prob,
        "away_win_prob": m.away_win_prob,
    }


def app_factory() -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    return create_app()
