"""League assistant: Claude with read-only tools over this app's league data.

The agent loop is manual so we can stream text to the browser as it's generated
and report which tool is running. Conversations are persisted as raw API message
params, so thinking and tool blocks are replayed to the model unchanged.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import anthropic
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select

from fantasy_gm.analytics.league import (
    LeagueData,
    load_league,
    player_json,
    positional_strength,
    power_rankings,
    waiver_suggestions,
)
from fantasy_gm.analytics.simulate import simulate
from fantasy_gm.analytics.trades import evaluate_trade, find_trades
from fantasy_gm.db import ChatMessage, Transaction, session_scope, utcnow

log = logging.getLogger(__name__)

MODEL = "claude-opus-5"
MAX_TOKENS = 64000
MAX_TOOL_ROUNDS = 12
FALLBACK_BETA = "server-side-fallback-2026-07-01"
NO_KEY_MESSAGE = (
    "No valid Anthropic API key. Add ANTHROPIC_API_KEY to backend/.env and restart the backend."
)

SYSTEM_PROMPT = """You are the league assistant inside Fantasy GM, a personal manager for an ESPN \
fantasy football league. You help the user (the owner of "my team") win: lineup calls, waiver \
pickups, trade targets and offers, and reading the league's analytics.

Ground every recommendation in the tools; they read the league data synced from ESPN. Numbers \
are fantasy points under this league's scoring. Key terms the tools use:
- value.per_game: expected points per game, blending ESPN's season projection with recent games.
- my_gain / their_gain (trades), ros_gain (waivers): change in points per week of a team's best \
lineup (plus a little bench depth).
- acceptance: rough 0-1 estimate that the other manager accepts a trade.
- power_score, all-play record, luck: see get_power_rankings.
- positional strength labels: "need" / "surplus" relative to the rest of the league.

Player locks: ESPN locks a player once his NFL game kicks off, and he can't be traded until the \
scoring week ends. Player objects carry "locked" and "game" (this week's game state). When the \
user asks for trades they can make now / today / right now, call find_trades with \
tradeable_now=true. Otherwise, if a suggested trade has tradeable_now=false, say it involves \
locked players and can only go through after the week's games finish.

The user is happy to pursue trades that favor them; still say how likely an offer is to be \
accepted and suggest how to pitch it. When a player or team name is ambiguous, look it up rather \
than guessing. Be concise and concrete: name players, give the numbers that matter, and end with \
a clear recommendation. The app is read-only; you can't make moves on ESPN, so tell the user what \
to do there."""


# --- tools ---------------------------------------------------------------------


class _NoArgs(BaseModel):
    model_config = {"extra": "forbid"}


class TeamArg(BaseModel):
    team: str | None = Field(
        None, description="Team name, abbreviation, owner name, or id. Omit for the user's team."
    )


class WaiverArgs(BaseModel):
    position: str | None = Field(None, description="QB, RB, WR, TE, K or D/ST to filter by.")
    limit: int = Field(10, ge=1, le=30)


class FreeAgentArgs(BaseModel):
    position: str | None = Field(None, description="QB, RB, WR, TE, K or D/ST.")
    limit: int = Field(15, ge=1, le=50)


class TradeSearchArgs(BaseModel):
    partner: str | None = Field(
        None, description="Only search trades with this team. Omit for all teams."
    )
    sort: str = Field(
        "balanced",
        pattern="^(balanced|gain|likely)$",
        description="balanced = gain times acceptance; gain = best for the user; likely = most likely accepted.",
    )
    limit: int = Field(8, ge=1, le=20)
    tradeable_now: bool = Field(
        False,
        description="Only players whose game this week hasn't started (not locked on ESPN), so "
        "the trade can be made right away.",
    )


class TradeEvalArgs(BaseModel):
    partner: str = Field(description="The other team.")
    give: list[str] = Field(
        min_length=1,
        max_length=4,
        description='Players the user sends, one list item each: ["Amon-Ra St. Brown", "Christian Watson"].',
    )
    get: list[str] = Field(
        min_length=1,
        max_length=4,
        description='Players the user receives, one list item each: ["Josh Allen"].',
    )

    @field_validator("give", "get", mode="before")
    @classmethod
    def _split_names(cls, v: Any) -> Any:
        # The model often sends "A, B" instead of ["A", "B"]; player names never contain commas.
        if isinstance(v, str):
            return [name.strip() for name in v.split(",") if name.strip()]
        return v


class PlayerArgs(BaseModel):
    name: str = Field(description="Player name (partial is fine).")


class TransactionArgs(BaseModel):
    team: str | None = None
    limit: int = Field(20, ge=1, le=100)


@dataclass
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    run: Callable[[LeagueContext, Any], Any]

    def definition(self) -> dict[str, Any]:
        schema = self.args.model_json_schema()
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)
        schema.setdefault("properties", {})
        # No eager_input_streaming: these inputs are a few short strings, so there is
        # nothing to gain from streaming them, and eager mode skips the API's input
        # validation. Evaluate_trade calls kept arriving as invalid JSON
        # ('"give": Amon-Ra…' instead of a list) with it on.
        return {"name": self.name, "description": self.description, "input_schema": schema}


class ToolError(Exception):
    """A tool failed in a way the model can recover from (bad name, etc.)."""


class LeagueContext:
    """League data loaded once per chat turn; tools read from it."""

    def __init__(self, data: LeagueData):
        self.data = data
        self._odds: dict | None = None

    @property
    def my_team_id(self) -> int:
        if self.data.league.my_team_id is None:
            raise ToolError(
                "The user's team isn't known (ESPN cookies not set). Ask which team is theirs."
            )
        return self.data.league.my_team_id

    def team_id(self, ref: str | None) -> int:
        if ref is None or not ref.strip():
            return self.my_team_id
        ref_l = ref.strip().lower()
        if ref_l.isdigit() and int(ref_l) in self.data.teams:
            return int(ref_l)
        teams = list(self.data.teams.values())
        for t in teams:
            if ref_l in {t.name.lower(), (t.abbrev or "").lower(), (t.owner_name or "").lower()}:
                return t.id
        partial = [
            t for t in teams if ref_l in t.name.lower() or ref_l in (t.owner_name or "").lower()
        ]
        if len(partial) == 1:
            return partial[0].id
        names = ", ".join(f"{t.name} ({t.owner_name})" for t in teams)
        raise ToolError(f"No single team matches {ref!r}. Teams: {names}")

    def team_name(self, tid: int | None) -> str | None:
        return self.data.teams[tid].name if tid in self.data.teams else None

    def find_player(self, ref: str, team_id: int | None = None) -> int:
        rows = [
            r
            for tid, rs in self.data.rosters.items()
            for r in rs
            if team_id is None or tid == team_id
        ]
        if ref.strip().isdigit():
            pid = int(ref)
            if any(r.player.id == pid for r in rows):
                return pid
        ref_l = ref.strip().lower()
        exact = [r for r in rows if r.player.full_name.lower() == ref_l]
        matches = exact or [r for r in rows if ref_l in r.player.full_name.lower()]
        if len(matches) == 1:
            return matches[0].player.id
        where = f" on {self.team_name(team_id)}" if team_id else ""
        if not matches:
            raise ToolError(f"No player matching {ref!r}{where}.")
        raise ToolError(
            f"{ref!r} is ambiguous{where}: " + ", ".join(m.player.full_name for m in matches[:8])
        )

    def odds(self) -> dict:
        if self._odds is None:
            self._odds = simulate(self.data)
        return self._odds


def _slim(p: dict) -> dict:
    v = p["value"]
    return {
        "id": p["id"],
        "name": p["name"],
        "pos": p["position"],
        "team": p["pro_team"],
        "injury": p["injury_status"] if p["injury_status"] not in (None, "ACTIVE") else None,
        "slot": p["slot"],
        "per_game": v["per_game"],
        "proj_this_week": v["this_week_projection"],
        "last4_avg": v["recent_avg"],
        "trend": v["trend"],
        "rostered_pct": p["percent_owned"],
        "locked": p["locked"],
        "game": _game_note(p["game"]),
    }


def _game_note(g: dict | None) -> str | None:
    if not g or g["state"] == "none":
        return None
    if g["state"] == "bye":
        return "bye"
    opp = f"{'vs' if g['is_home'] else '@'} {g['opponent']}"
    if g["state"] == "pre":
        kickoff = g["kickoff"].isoformat() if g["kickoff"] else "TBD"
        return f"not started ({opp}, kickoff {kickoff})"
    score = f"{g['team_score']}-{g['opponent_score']}"
    return f"{'in progress' if g['state'] == 'in' else 'final'} {score} {opp}"


def t_overview(ctx: LeagueContext, _: _NoArgs) -> dict:
    lg = ctx.data.league
    return {
        "league": lg.name,
        "season": lg.season,
        "current_week": lg.current_week,
        "regular_season_weeks": lg.final_regular_week,
        "settings": lg.settings,
        "my_team": ctx.team_name(lg.my_team_id),
        "standings": [
            {
                "id": t.id,
                "team": t.name,
                "owner": t.owner_name,
                "record": f"{t.wins}-{t.losses}-{t.ties}",
                "points_for": round(t.points_for, 1),
                "seed": t.playoff_seed,
            }
            for t in sorted(ctx.data.teams.values(), key=lambda t: t.playoff_seed or 99)
        ],
        "this_week": [
            {
                "home": ctx.team_name(m.home_team_id),
                "away": ctx.team_name(m.away_team_id),
                "home_points": m.home_points,
                "away_points": m.away_points,
                "home_projected": m.home_projected,
                "away_projected": m.away_projected,
            }
            for m in ctx.data.matchups
            if m.week == lg.current_week
        ],
    }


def t_power(ctx: LeagueContext, _: _NoArgs) -> list[dict]:
    return [
        {
            "rank": r["rank"],
            "team": ctx.team_name(r["team_id"]),
            "power_score": r["power_score"],
            "components_0_100": r["components"],
            "all_play": r["all_play"],
            "expected_wins": r["expected_wins"],
            "actual_wins": r["actual_wins"],
            "luck": r["luck"],
            "roster_strength_pts_per_week": r["roster_strength"],
        }
        for r in power_rankings(ctx.data)
    ]


def t_roster(ctx: LeagueContext, args: TeamArg) -> dict:
    tid = ctx.team_id(args.team)
    rows = sorted(ctx.data.rosters.get(tid, []), key=lambda r: -r.value.per_game)
    return {
        "team": ctx.team_name(tid),
        "is_users_team": tid == ctx.data.league.my_team_id,
        "players": [_slim(player_json(r)) for r in rows],
        "positional_strength": positional_strength(ctx.data)[tid],
    }


def t_positions(ctx: LeagueContext, _: _NoArgs) -> dict:
    return {
        ctx.team_name(tid): {pos: f"#{c['rank']} {c['label']}" for pos, c in cells.items()}
        for tid, cells in positional_strength(ctx.data).items()
    }


def t_waivers(ctx: LeagueContext, args: WaiverArgs) -> list[dict]:
    out = waiver_suggestions(ctx.data, ctx.my_team_id, limit=100)
    if args.position:
        out = [s for s in out if s["player"]["position"] == args.position.upper()]
    return [
        {
            "add": _slim(s["player"]),
            "ros_gain_per_week": s["ros_gain"],
            "this_week_gain": s["week_gain"],
            "drop": _slim(s["drop"]) if s["drop"] else None,
        }
        for s in out[: args.limit]
    ]


def t_free_agents(ctx: LeagueContext, args: FreeAgentArgs) -> list[dict]:
    rows = [
        r
        for r in ctx.data.free_agents
        if not args.position or r.player.position == args.position.upper()
    ]
    rows.sort(key=lambda r: r.value.per_game, reverse=True)
    return [_slim(player_json(r)) for r in rows[: args.limit]]


def _trade_out(ctx: LeagueContext, t: dict) -> dict:
    return {
        "partner": ctx.team_name(t["partner_team_id"]),
        "give": [_slim(p) for p in t["give"]],
        "get": [_slim(p) for p in t["get"]],
        "my_gain_per_week": t["my_gain"],
        "their_gain_per_week": t["their_gain"],
        "raw_value_edge": t["raw_value_edge"],
        "acceptance": t["acceptance"],
        "verdict": t["verdict"],
        "my_forced_drops": [p["name"] for p in t["my_drops"]],
        "tradeable_now": t["tradeable_now"],
    }


def t_find_trades(ctx: LeagueContext, args: TradeSearchArgs) -> list[dict]:
    partner = ctx.team_id(args.partner) if args.partner else None
    trades = find_trades(
        ctx.data,
        ctx.my_team_id,
        partner,
        limit=args.limit,
        sort=args.sort,  # type: ignore[arg-type]
        tradeable_now=args.tradeable_now,
    )
    return [_trade_out(ctx, t) for t in trades]


def t_eval_trade(ctx: LeagueContext, args: TradeEvalArgs) -> dict:
    partner = ctx.team_id(args.partner)
    me = ctx.my_team_id
    give = [ctx.find_player(p, me) for p in args.give]
    get = [ctx.find_player(p, partner) for p in args.get]
    t = evaluate_trade(ctx.data, me, partner, give, get)
    return _trade_out(ctx, t)


def t_odds(ctx: LeagueContext, _: _NoArgs) -> list[dict]:
    odds = ctx.odds()
    return sorted(
        ({"team": ctx.team_name(tid), **o} for tid, o in odds.items()),
        key=lambda r: -r["playoff_pct"],
    )


def t_player(ctx: LeagueContext, args: PlayerArgs) -> list[dict]:
    q = args.name.strip().lower()
    rows = [r for rs in ctx.data.rosters.values() for r in rs] + ctx.data.free_agents
    hits = [r for r in rows if q in r.player.full_name.lower()][:5]
    if not hits:
        raise ToolError(
            f"No player matching {args.name!r} among rostered players and top free agents."
        )
    return [
        {**_slim(player_json(r)), "fantasy_team": ctx.team_name(r.team_id) or "available"}
        for r in hits
    ]


def t_transactions(ctx: LeagueContext, args: TransactionArgs) -> list[dict]:
    tid = ctx.team_id(args.team) if args.team else None
    names = {r.player.id: r.player.full_name for rs in ctx.data.rosters.values() for r in rs}
    names |= {r.player.id: r.player.full_name for r in ctx.data.free_agents}
    with session_scope() as s:
        q = select(Transaction).where(
            Transaction.league_id == ctx.data.league.id, Transaction.status == "EXECUTED"
        )
        txns = list(s.scalars(q.order_by(Transaction.proposed_at.desc().nullslast()).limit(300)))
    out = []
    for t in txns:
        involved = (
            {t.team_id}
            | {i.get("from_team_id") for i in t.items}
            | {i.get("to_team_id") for i in t.items}
        )
        if tid is not None and tid not in involved:
            continue
        out.append(
            {
                "type": t.type,
                "team": ctx.team_name(t.team_id),
                "week": t.week,
                "bid": t.bid_amount,
                "items": [
                    f"{i['type']} {names.get(i.get('player_id'), i.get('player_external_id'))}"
                    + (
                        f" ({ctx.team_name(i.get('from_team_id'))} → {ctx.team_name(i.get('to_team_id'))})"
                        if i["type"] == "TRADE"
                        else ""
                    )
                    for i in t.items
                ],
            }
        )
        if len(out) >= args.limit:
            break
    return out


TOOLS = [
    Tool(
        "get_league_overview",
        "League settings, standings, and this week's matchups.",
        _NoArgs,
        t_overview,
    ),
    Tool(
        "get_power_rankings",
        "Power rankings with all-play record, expected wins, luck and roster strength.",
        _NoArgs,
        t_power,
    ),
    Tool(
        "get_team_roster",
        "A team's roster with player values, injuries and the team's positional strength.",
        TeamArg,
        t_roster,
    ),
    Tool(
        "get_positional_strength",
        "Every team's league rank and need/surplus label at each position. Use to find trade partners whose surplus matches the user's need.",
        _NoArgs,
        t_positions,
    ),
    Tool(
        "get_waiver_suggestions",
        "Free agents ranked by how much they improve the user's best lineup, with a suggested drop.",
        WaiverArgs,
        t_waivers,
    ),
    Tool(
        "get_free_agents",
        "Best available players by expected points per game.",
        FreeAgentArgs,
        t_free_agents,
    ),
    Tool(
        "find_trades",
        "Search trades (1-for-1 up to 2-for-2) that improve the user's team, with acceptance odds.",
        TradeSearchArgs,
        t_find_trades,
    ),
    Tool(
        "evaluate_trade",
        "Evaluate a specific trade between the user's team and another team.",
        TradeEvalArgs,
        t_eval_trade,
    ),
    Tool(
        "get_playoff_odds",
        "Simulated playoff, bye, #1 seed and championship odds for every team.",
        _NoArgs,
        t_odds,
    ),
    Tool(
        "find_player",
        "Look up players by name across all rosters and available players.",
        PlayerArgs,
        t_player,
    ),
    Tool(
        "get_transactions",
        "Recent executed adds, drops and trades, optionally for one team.",
        TransactionArgs,
        t_transactions,
    ),
]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}
TOOL_LABELS = {
    "get_league_overview": "Reading standings",
    "get_power_rankings": "Checking power rankings",
    "get_team_roster": "Reading roster",
    "get_positional_strength": "Comparing positional strength",
    "get_waiver_suggestions": "Scanning waivers",
    "get_free_agents": "Scanning free agents",
    "find_trades": "Searching trades",
    "evaluate_trade": "Evaluating trade",
    "get_playoff_odds": "Simulating the season",
    "find_player": "Looking up player",
    "get_transactions": "Reading transactions",
}


def run_tool(ctx: LeagueContext, name: str, raw_input: Any) -> tuple[str, bool]:
    """Execute a tool; returns (content, is_error). Never raises for model mistakes."""
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        return f"Unknown tool {name!r}.", True
    try:
        args = tool.args.model_validate(raw_input if isinstance(raw_input, dict) else {})
    except ValidationError as e:
        return json.dumps(
            {"INVALID_INPUT": e.errors(include_url=False, include_context=False)}, default=str
        ), True
    try:
        return json.dumps(tool.run(ctx, args), default=str), False
    except (ToolError, ValueError) as e:
        return str(e), True


# --- agent loop ----------------------------------------------------------------


def _block_params(content: list[Any]) -> list[dict[str, Any]]:
    """Assistant content -> params to replay, handling mid-output fallback boundaries.

    After a mid-output fallback, thinking/tool_use blocks before the last fallback
    block must not be echoed back.
    """
    blocks = [b.model_dump(mode="json", by_alias=True, exclude_none=True) for b in content]
    last_fb = max((i for i, b in enumerate(blocks) if b.get("type") == "fallback"), default=None)
    if last_fb is None:
        return blocks
    drop = {"thinking", "redacted_thinking", "tool_use", "server_tool_use"}
    return [b for i, b in enumerate(blocks) if i >= last_fb or b.get("type") not in drop]


def _system(ctx: LeagueContext) -> list[dict[str, Any]]:
    lg = ctx.data.league
    states = [g.state for g in ctx.data.pro_games]
    games_line = (
        f" NFL games this week: {states.count('post')} final, {states.count('in')} in progress, "
        f"{states.count('pre')} not started."
        if states
        else ""
    )
    league_line = (
        f"League: {lg.name} ({lg.season}), week {lg.current_week} of {lg.final_regular_week}. "
        f"User's team: {ctx.team_name(lg.my_team_id) or 'unknown'}. "
        f"Today: {utcnow():%a %Y-%m-%d} (UTC).{games_line}"
    )
    return [{"type": "text", "text": SYSTEM_PROMPT}, {"type": "text", "text": league_line}]


def load_history(conversation_id: str) -> list[dict[str, Any]]:
    with session_scope() as s:
        rows = s.scalars(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.id)
        )
        return [{"role": r.role, "content": r.content} for r in rows]


def _save(league_id: int, conversation_id: str, role: str, content: Any) -> None:
    with session_scope() as s:
        s.add(
            ChatMessage(
                league_id=league_id, conversation_id=conversation_id, role=role, content=content
            )
        )


def _answer_unrun(league_id: int, conversation_id: str, history: list, content: list[dict]) -> None:
    results = [
        {
            "type": "tool_result",
            "tool_use_id": b["id"],
            "content": "Not run: the turn ended early.",
            "is_error": True,
        }
        for b in content
        if b["type"] == "tool_use"
    ]
    history.append({"role": "user", "content": results})
    _save(league_id, conversation_id, "user", results)


def run_chat(
    client: anthropic.Anthropic, league_id: int, conversation_id: str, user_text: str
) -> Iterator[dict[str, Any]]:
    """Run one user turn. Yields UI events: text, tool, error, done."""
    with session_scope() as s:
        data = load_league(s, league_id)
    if data is None:
        yield {"type": "error", "message": "League not found."}
        return
    ctx = LeagueContext(data)
    history = load_history(conversation_id)
    user_msg = {"role": "user", "content": [{"type": "text", "text": user_text}]}
    history.append(user_msg)
    _save(league_id, conversation_id, "user", user_msg["content"])
    tools = [t.definition() for t in TOOLS]

    json_retries = 0
    for _ in range(MAX_TOOL_ROUNDS):
        try:
            with client.beta.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=_system(ctx),
                tools=tools,
                messages=history,
                thinking={"type": "adaptive"},
                cache_control={"type": "ephemeral"},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                for event in stream:
                    if event.type == "text":
                        yield {"type": "text", "text": event.text}
                    elif (
                        event.type == "content_block_start"
                        and event.content_block.type == "tool_use"
                    ):
                        name = event.content_block.name
                        yield {"type": "tool", "name": name, "label": TOOL_LABELS.get(name, name)}
                response = stream.get_final_message()
            json_retries = 0
        except ValueError:
            # Tool input JSON the SDK couldn't parse at all: re-issue the turn (bounded).
            log.warning("Unparseable model response (attempt %d)", json_retries + 1, exc_info=True)
            json_retries += 1
            if json_retries > 2:
                yield {
                    "type": "error",
                    "message": "The model produced an unreadable tool call. Try again.",
                }
                return
            continue
        except TypeError as e:
            if "authentication method" not in str(e):
                raise
            # The SDK raises TypeError when no credentials are configured at all.
            yield {"type": "error", "message": NO_KEY_MESSAGE}
            return
        except anthropic.AuthenticationError:
            yield {
                "type": "error",
                "message": "Anthropic API key missing or invalid. Set ANTHROPIC_API_KEY in backend/.env.",
            }
            return
        except anthropic.RateLimitError:
            yield {
                "type": "error",
                "message": "Rate limited by the Anthropic API. Wait a moment and try again.",
            }
            return
        except anthropic.APIStatusError as e:
            log.exception("Anthropic API error")
            yield {"type": "error", "message": f"Anthropic API error ({e.status_code})."}
            return
        except anthropic.APIConnectionError:
            yield {"type": "error", "message": "Couldn't reach the Anthropic API."}
            return
        except anthropic.AnthropicError as e:  # e.g. no credentials configured at all
            yield {"type": "error", "message": f"Anthropic client error: {e}"}
            return

        assistant = {"role": "assistant", "content": _block_params(response.content)}
        history.append(assistant)
        _save(league_id, conversation_id, "assistant", assistant["content"])

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason in ("refusal", "max_tokens"):
            # A tool call may have been cut off mid-input: never run it, but answer it so
            # the stored history stays valid (append-only; earlier turns are never edited).
            if any(b["type"] == "tool_use" for b in assistant["content"]):
                _answer_unrun(league_id, conversation_id, history, assistant["content"])
            reason = (
                "declined to answer that" if response.stop_reason == "refusal" else "was cut off"
            )
            yield {"type": "error", "message": f"Claude {reason}."}
            break
        if response.stop_reason == "pause_turn":
            continue
        if not tool_uses:
            break

        results = []
        for block in tool_uses:
            content, is_error = run_tool(ctx, block.name, block.input)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                    "is_error": is_error,
                }
            )
        tool_msg = {"role": "user", "content": results}
        history.append(tool_msg)
        _save(league_id, conversation_id, "user", results)
    else:
        yield {"type": "error", "message": "Stopped after too many tool calls."}
    yield {"type": "done"}


def transcript(conversation_id: str) -> list[dict[str, Any]]:
    """User-visible transcript: user text and assistant text only."""
    out: list[dict[str, Any]] = []
    for m in load_history(conversation_id):
        texts = [b.get("text", "") for b in m["content"] if b.get("type") == "text"]
        if not texts:
            continue
        text = "".join(texts)
        if out and out[-1]["role"] == m["role"] == "assistant":
            out[-1]["text"] += "\n\n" + text
        else:
            out.append({"role": m["role"], "text": text})
    return out
