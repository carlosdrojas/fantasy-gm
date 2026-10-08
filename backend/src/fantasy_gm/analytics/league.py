"""League-level analytics built from stored data (the API's read model)."""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from fantasy_gm.analytics.lineup import LineupPlayer, lineup_total, optimal_lineup
from fantasy_gm.analytics.power import GameResult, all_play, power_scores
from fantasy_gm.analytics.values import PlayerValue, player_value
from fantasy_gm.db import League, Matchup, Player, PlayerPoints, ProGame, RosterEntry, Team

POSITIONS = ["QB", "RB", "WR", "TE", "K", "D/ST"]
DEPTH_WEIGHT = 0.25  # best bench player's share of a position's strength
NEED_Z = -0.5
SURPLUS_Z = 0.5


@dataclass
class PlayerRow:
    player: Player
    value: PlayerValue
    slot: str | None = None  # None when not rostered
    team_id: int | None = None
    game: dict | None = None  # this week's NFL game from the player's side (see game_view)

    @property
    def locked(self) -> bool:
        """ESPN locks a player once his game kicks off; he can't be traded, dropped or
        moved until the scoring week ends."""
        return self.game is not None and self.game["state"] in ("in", "post")

    def lineup_player(self, *, this_week: bool = False) -> LineupPlayer:
        v = self.value.this_week_projection if this_week else self.value.per_game
        return LineupPlayer(
            player_id=self.player.id,
            eligible_slots=tuple(self.player.eligible_slots or [self.player.position]),
            value=v or 0.0,
            injury_status=self.player.injury_status,
            on_ir=self.slot == "IR",
        )


@dataclass
class LeagueData:
    league: League
    teams: dict[int, Team]
    rosters: dict[int, list[PlayerRow]]
    free_agents: list[PlayerRow]
    matchups: list[Matchup]
    slot_counts: dict[str, int] = field(default_factory=dict)
    pro_games: list[ProGame] = field(default_factory=list)  # this week's NFL games


def load_league(session: Session, league_id: int) -> LeagueData | None:
    league = session.get(League, league_id)
    if league is None:
        return None
    teams = {t.id: t for t in session.scalars(select(Team).where(Team.league_id == league_id))}

    points: dict[int, dict[tuple[int, str], float]] = defaultdict(dict)
    for pp in session.scalars(
        select(PlayerPoints).where(
            PlayerPoints.league_id == league_id, PlayerPoints.season == league.season
        )
    ):
        points[pp.player_id][(pp.week, pp.kind)] = pp.points

    entries = list(session.scalars(select(RosterEntry).where(RosterEntry.league_id == league_id)))
    rostered_ids = {e.player_id for e in entries}
    player_ids = rostered_ids | set(points)
    players = (
        {p.id: p for p in session.scalars(select(Player).where(Player.id.in_(player_ids)))}
        if player_ids
        else {}
    )

    week = league.current_week
    pro_games = (
        list(
            session.scalars(
                select(ProGame).where(ProGame.season == league.season, ProGame.week == week)
            )
        )
        if week
        else []
    )
    games = games_by_team(pro_games)

    def game(p: Player) -> dict | None:
        return game_view(games, p.pro_team) if pro_games else None

    rosters: dict[int, list[PlayerRow]] = {t: [] for t in teams}
    for e in entries:
        p = players[e.player_id]
        rosters[e.team_id].append(
            PlayerRow(
                p,
                player_value(points.get(p.id, {}), week),
                slot=e.slot,
                team_id=e.team_id,
                game=game(p),
            )
        )
    free_agents = [
        PlayerRow(players[pid], player_value(points[pid], week), game=game(players[pid]))
        for pid in points
        if pid not in rostered_ids and pid in players
    ]
    matchups = list(
        session.scalars(
            select(Matchup).where(Matchup.league_id == league_id).order_by(Matchup.week)
        )
    )
    return LeagueData(
        league=league,
        teams=teams,
        rosters=rosters,
        free_agents=free_agents,
        matchups=matchups,
        slot_counts=dict((league.settings or {}).get("lineup_slot_counts") or {}),
        pro_games=pro_games,
    )


# --- live games -----------------------------------------------------------------


def games_by_team(games: list[ProGame]) -> dict[str, ProGame]:
    out: dict[str, ProGame] = {}
    for g in games:
        out[g.home_team] = out[g.away_team] = g
    return out


def game_view(games: dict[str, ProGame], pro_team: str | None) -> dict:
    """A player's NFL game this week, from his team's side. ``state`` 'bye' if none."""
    g = games.get(pro_team or "")
    if g is None:
        return {"state": "bye" if pro_team and pro_team != "FA" else "none"}
    home = g.home_team == pro_team
    return {
        "state": g.state,
        "detail": g.detail,
        "kickoff": g.kickoff,
        "opponent": g.away_team if home else g.home_team,
        "is_home": home,
        "team_score": g.home_score if home else g.away_score,
        "opponent_score": g.away_score if home else g.home_score,
    }


STARTER_EXCLUDED_SLOTS = ("BE", "IR")


def lineup_status(rows: list[PlayerRow]) -> dict[str, int]:
    """How many of a team's starters have played, are playing, or have yet to play."""
    counts = {"played": 0, "playing": 0, "yet_to_play": 0}
    for r in rows:
        if r.slot in STARTER_EXCLUDED_SLOTS or r.game is None:
            continue
        state = r.game["state"]
        if state == "post":
            counts["played"] += 1
        elif state == "in":
            counts["playing"] += 1
        elif state == "pre":
            counts["yet_to_play"] += 1
    return counts


# --- power rankings -----------------------------------------------------------


def completed_results(matchups: list[Matchup]) -> list[GameResult]:
    results: list[GameResult] = []
    for m in matchups:
        if m.is_playoff or m.winner == "UNDECIDED" or m.away_team_id is None:
            continue
        if m.home_points is None or m.away_points is None:
            continue
        tie = m.winner == "TIE"
        results.append(
            GameResult(m.week, m.home_team_id, m.home_points, None if tie else m.winner == "HOME")
        )
        results.append(
            GameResult(m.week, m.away_team_id, m.away_points, None if tie else m.winner == "AWAY")
        )
    return results


def roster_strength(data: LeagueData, team_id: int) -> float:
    lineup = optimal_lineup(
        [r.lineup_player() for r in data.rosters.get(team_id, [])],
        data.slot_counts,
        respect_injuries=False,
    )
    return lineup_total(lineup)


def power_rankings(data: LeagueData) -> list[dict]:
    power = all_play(completed_results(data.matchups))
    strength = {t: roster_strength(data, t) for t in data.teams}
    scores = power_scores(power, strength)
    rows = []
    for tid, team in data.teams.items():
        tp = power.get(tid)
        rows.append(
            {
                "team_id": tid,
                "power_score": scores[tid]["score"],
                "components": {k: v for k, v in scores[tid].items() if k != "score"},
                "roster_strength": strength[tid],
                "all_play": {
                    "wins": tp.all_play_wins if tp else 0,
                    "losses": tp.all_play_losses if tp else 0,
                    "ties": tp.all_play_ties if tp else 0,
                    "pct": round(tp.all_play_pct, 3) if tp else 0.0,
                },
                "actual_wins": tp.actual_wins if tp else 0.0,
                "expected_wins": tp.expected_wins if tp else 0.0,
                "luck": tp.luck if tp else 0.0,
                "weekly_points": [
                    {"week": w, "points": p}
                    for w, p in sorted((tp.weekly_points if tp else {}).items())
                ],
                "record": {"wins": team.wins, "losses": team.losses, "ties": team.ties},
                "points_for": team.points_for,
            }
        )
    rows.sort(key=lambda r: r["power_score"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


# --- positional strength / needs ---------------------------------------------


def positional_strength(data: LeagueData) -> dict[int, dict[str, dict]]:
    """Per team, per position: starter value, depth, league z-score, and a label.

    Starters are the season-long optimal lineup; each starter is credited to their
    own position (so a FLEX RB counts toward RB).
    """
    raw: dict[int, dict[str, dict[str, float]]] = {}
    for tid in data.teams:
        rows = data.rosters.get(tid, [])
        lineup = optimal_lineup(
            [r.lineup_player() for r in rows], data.slot_counts, respect_injuries=False
        )
        starters = {p.player_id for ps in lineup.values() for p in ps}
        by_pos: dict[str, dict[str, float]] = {
            pos: {"starters": 0.0, "depth": 0.0} for pos in POSITIONS
        }
        for r in rows:
            pos = r.player.position
            if pos not in by_pos:
                continue
            if r.player.id in starters:
                by_pos[pos]["starters"] += r.value.per_game
            elif r.slot != "IR":
                by_pos[pos]["depth"] = max(by_pos[pos]["depth"], r.value.per_game)
        raw[tid] = by_pos

    out: dict[int, dict[str, dict]] = {tid: {} for tid in raw}
    for pos in POSITIONS:
        scores = {
            tid: v[pos]["starters"] + DEPTH_WEIGHT * v[pos]["depth"] for tid, v in raw.items()
        }
        mean = statistics.fmean(scores.values()) if scores else 0.0
        sd = statistics.pstdev(scores.values()) if len(scores) > 1 else 0.0
        ranked = sorted(scores, key=scores.get, reverse=True)  # type: ignore[arg-type]
        for tid, score in scores.items():
            z = (score - mean) / sd if sd else 0.0
            out[tid][pos] = {
                "starters": round(raw[tid][pos]["starters"], 2),
                "depth": round(raw[tid][pos]["depth"], 2),
                "score": round(score, 2),
                "z": round(z, 2),
                "rank": ranked.index(tid) + 1,
                "label": "need" if z <= NEED_Z else "surplus" if z >= SURPLUS_Z else "ok",
            }
    return out


# --- waiver suggestions -------------------------------------------------------

MAX_FA_CANDIDATES = 150


def waiver_suggestions(data: LeagueData, team_id: int, limit: int = 25) -> list[dict]:
    """Free agents ranked by how much they improve this team's optimal lineup.

    ``ros_gain``: season-long lineup gain per week (blended value).
    ``week_gain``: gain for this week's lineup using this week's projections.
    Each suggestion names the bench player you'd most sensibly drop.
    """
    roster = data.rosters.get(team_id, [])
    if not roster:
        return []
    slots = data.slot_counts

    def total(rows: list[PlayerRow], this_week: bool) -> tuple[float, set[int]]:
        lineup = optimal_lineup(
            [r.lineup_player(this_week=this_week) for r in rows], slots, respect_injuries=this_week
        )
        return lineup_total(lineup), {p.player_id for ps in lineup.values() for p in ps}

    base_ros, _ = total(roster, False)
    base_week, _ = total(roster, True)

    candidates = sorted(data.free_agents, key=lambda r: r.value.per_game, reverse=True)
    # Players on injured reserve can't help a lineup for weeks; their blended value
    # (often recent production only) would otherwise rank them first.
    candidates = [
        c
        for c in candidates
        if c.player.position in POSITIONS and c.player.injury_status != "INJURY_RESERVE"
    ][:MAX_FA_CANDIDATES]

    suggestions = []
    for fa in candidates:
        with_fa = [*roster, fa]
        ros_total, ros_starters = total(with_fa, False)
        week_total, _ = total(with_fa, True)
        ros_gain = round(ros_total - base_ros, 2)
        week_gain = round(week_total - base_week, 2)
        if ros_gain <= 0 and week_gain <= 0:
            continue
        # Drop candidate: lowest-value non-starter, never an IR stash.
        droppable = [r for r in roster if r.player.id not in ros_starters and r.slot != "IR"]
        drop = min(droppable, key=lambda r: r.value.per_game, default=None)
        suggestions.append(
            {
                "player": player_json(fa),
                "ros_gain": ros_gain,
                "week_gain": week_gain,
                "drop": player_json(drop) if drop else None,
                "score": round(ros_gain + 0.5 * week_gain + 0.1 * max(fa.value.trend or 0, 0), 2),
            }
        )
    suggestions.sort(key=lambda s: s["score"], reverse=True)
    return suggestions[:limit]


def player_json(r: PlayerRow) -> dict:
    p, v = r.player, r.value
    return {
        "id": p.id,
        "external_id": p.external_id,
        "name": p.full_name,
        "position": p.position,
        "pro_team": p.pro_team,
        "injury_status": p.injury_status,
        "slot": r.slot,
        "team_id": r.team_id,
        "percent_owned": p.percent_owned,
        "percent_owned_change": p.percent_owned_change,
        "value": {
            "per_game": v.per_game,
            "projected_per_game": v.projected_per_game,
            "recent_avg": v.recent_avg,
            "this_week_projection": v.this_week_projection,
            "this_week_actual": v.this_week_actual,
            "trend": v.trend,
        },
        "game": r.game,
        "locked": r.locked,
    }
