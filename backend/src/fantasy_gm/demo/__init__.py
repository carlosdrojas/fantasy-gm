"""A made-up league for the public demo, built from real NFL players and points.

``pool.json`` holds real players with their real weekly fantasy points (refresh it with
``scripts/export_demo_pool.py``). Everything else is invented: ten fictional managers
draft from that pool, set lineups, make waiver claims, and play a schedule, all driven
by a seeded RNG so the league comes out identical on every build. Scores are the real
points of whoever each team started that week.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from importlib import resources

from fantasy_gm.analytics.lineup import LineupPlayer, optimal_lineup
from fantasy_gm.domain import (
    LeagueSnapshot,
    MatchupData,
    PlayerData,
    RosterSlotData,
    TeamData,
    TransactionData,
    TransactionItemData,
)

PLATFORM = "demo"
EXTERNAL_ID = "demo"
LEAGUE_NAME = "Gridiron Think Tank (demo)"
SEED = 2026
MY_TEAM = "1"  # 1-3 despite a top-three roster: plenty for the dashboard to work on

SLOT_COUNTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "D/ST": 1, "K": 1, "BE": 6, "IR": 1}
REGULAR_SEASON_WEEKS = 14
PLAYOFF_TEAMS = 4
SEASON_GAMES = 17

# (team name, abbrev, manager). All fictional.
TEAMS = [
    ("Fourth & Long Shots", "4LS", "You (demo)"),
    ("Taco Tuesday Tacklers", "TTT", "Marcus Bell"),
    ("The Waiver Wire Wizards", "WWW", "Priya Raman"),
    ("Bye Week Blues", "BWB", "Chris Albright"),
    ("Hail Mary Hopefuls", "HMH", "Jordan Okafor"),
    ("Red Zone Regulars", "RZR", "Sam Castillo"),
    ("Pocket Presence", "PKT", "Elena Novak"),
    ("Two-Minute Drill", "TMD", "Dana Whitfield"),
    ("Sunday Scaries", "SSC", "Taylor Nguyen"),
    ("Pick Six Society", "P6S", "Riley Brennan"),
]

ROUNDS = sum(n for s, n in SLOT_COUNTS.items() if s != "IR")
# Most of each position a manager will draft, and the fewest they must end up with.
DRAFT_MAX = {"QB": 2, "RB": 6, "WR": 6, "TE": 2, "K": 1, "D/ST": 1}
DRAFT_MIN = {"QB": 1, "RB": 3, "WR": 3, "TE": 1, "K": 1, "D/ST": 1}
LATE_ROUND_ONLY = {"K", "D/ST"}  # nobody takes these before the last rounds
WAIVER_CLAIM_RATE = 0.55  # chance a manager makes a claim in a given week


@dataclass
class Pool:
    season: int
    current_week: int
    players: dict[str, PlayerData]


def load_pool() -> Pool:
    raw = json.loads(resources.files(__package__).joinpath("pool.json").read_text())
    players = {}
    for p in raw["players"]:
        points = {}
        for key, v in p["points"].items():
            week, kind = key.split(":")
            points[(int(week), kind)] = v
        players[p["id"]] = PlayerData(
            external_id=p["id"],
            full_name=p["name"],
            position=p["position"],
            pro_team=p["pro_team"],
            injury_status=p["injury_status"],
            eligible_slots=p["eligible_slots"],
            percent_owned=p["percent_owned"],
            points=points,
        )
    return Pool(raw["season"], raw["current_week"], players)


@dataclass
class _Team:
    ext: str
    roster: list[str] = field(default_factory=list)
    claimed: set[str] = field(default_factory=set)  # picked up on waivers
    wins: int = 0
    losses: int = 0
    ties: int = 0
    points_for: float = 0.0
    points_against: float = 0.0


def build_snapshot(pool: Pool | None = None, seed: int = SEED) -> LeagueSnapshot:
    pool = pool or load_pool()
    rng = random.Random(seed)
    players = pool.players
    week_now = pool.current_week
    start = _season_start(pool.season)

    def proj(pid: str) -> float:
        return players[pid].points.get((0, "projected")) or 0.0

    def manager_value(pid: str, week: int) -> float:
        """What a manager believes a player is worth going into ``week``."""
        p = players[pid].points
        recent = [p[(w, "actual")] for w in range(max(1, week - 3), week) if (w, "actual") in p]
        base = proj(pid) / SEASON_GAMES
        played = [x for x in recent if x]
        return 0.7 * base + 0.3 * (sum(played) / len(played)) if played else base

    teams = [_Team(str(i + 1)) for i in range(len(TEAMS))]
    _draft(rng, teams, players, proj)

    # Week by week: waiver claims (from week 2), then lineups and real scores.
    schedule = _schedule(rng, [t.ext for t in teams], REGULAR_SEASON_WEEKS)
    by_ext = {t.ext: t for t in teams}
    transactions: list[TransactionData] = []
    matchups: list[MatchupData] = []
    for week in range(1, REGULAR_SEASON_WEEKS + 1):
        if 2 <= week <= week_now:
            transactions += _waivers(rng, teams, players, week, manager_value, start)
        for i, (home, away) in enumerate(schedule[week - 1]):
            m = MatchupData(
                external_id=f"{week}-{i + 1}",
                week=week,
                home_team_external_id=home,
                away_team_external_id=away,
                home_points=None,
                away_points=None,
                home_projected=None,
                away_projected=None,
                winner="UNDECIDED",
                is_playoff=False,
            )
            if week < week_now:
                h = _score(by_ext[home].roster, players, week, manager_value)
                a = _score(by_ext[away].roster, players, week, manager_value)
                m.home_points, m.away_points = h, a
                m.winner = "HOME" if h > a else "AWAY" if a > h else "TIE"
                _record(by_ext[home], h, a)
                _record(by_ext[away], a, h)
            elif week == week_now:
                m.home_points = m.away_points = 0.0
                m.home_projected = _projected(by_ext[home].roster, players, week)
                m.away_projected = _projected(by_ext[away].roster, players, week)
            matchups.append(m)

    standings = sorted(teams, key=lambda t: (-(t.wins + 0.5 * t.ties), -t.points_for))
    seeds = {t.ext: i + 1 for i, t in enumerate(standings)}
    team_data = [
        TeamData(
            external_id=t.ext,
            name=TEAMS[i][0],
            abbrev=TEAMS[i][1],
            owner_name=TEAMS[i][2],
            owner_ids=[f"demo-owner-{t.ext}"],
            wins=t.wins,
            losses=t.losses,
            ties=t.ties,
            points_for=round(t.points_for, 2),
            points_against=round(t.points_against, 2),
            playoff_seed=seeds[t.ext],
            waiver_rank=len(teams) + 1 - seeds[t.ext],
            roster=_set_lineup(t, players, week_now, manager_value),
        )
        for i, t in enumerate(teams)
    ]
    return LeagueSnapshot(
        platform=PLATFORM,
        external_id=EXTERNAL_ID,
        season=pool.season,
        name=LEAGUE_NAME,
        current_week=week_now,
        final_regular_week=REGULAR_SEASON_WEEKS,
        settings={
            "lineup_slot_counts": SLOT_COUNTS,
            "scoring_type": "H2H_POINTS",
            "reception_points": 1.0,
            "regular_season_weeks": REGULAR_SEASON_WEEKS,
            "playoff_team_count": PLAYOFF_TEAMS,
            "uses_faab": False,
            "team_count": len(teams),
            "demo": True,
        },
        my_team_external_id=MY_TEAM,
        teams=team_data,
        players=list(players.values()),
        matchups=matchups,
        transactions=transactions,
    )


# --- draft ----------------------------------------------------------------------


def _draft(rng: random.Random, teams: list[_Team], players: dict[str, PlayerData], proj) -> None:
    """Snake draft. Each manager has a noisy board (ADP-style) and respects position needs."""
    board = {
        t.ext: {pid: proj(pid) * rng.lognormvariate(0, 0.15) for pid in players} for t in teams
    }
    taken: set[str] = set()
    for rnd in range(ROUNDS):
        order = teams if rnd % 2 == 0 else list(reversed(teams))
        for t in order:
            counts = _position_counts(t.roster, players)
            picks_left = ROUNDS - rnd
            unmet = {pos: n - counts.get(pos, 0) for pos, n in DRAFT_MIN.items()}
            must = {pos for pos, n in unmet.items() if n > 0}
            forced = sum(max(n, 0) for n in unmet.values()) >= picks_left

            def allowed(pid: str, t=t, counts=counts, must=must, forced=forced, rnd=rnd) -> bool:
                pos = players[pid].position
                if counts.get(pos, 0) >= DRAFT_MAX[pos]:
                    return False
                if pos in LATE_ROUND_ONLY and rnd < ROUNDS - 3 and not forced:
                    return False
                return not forced or pos in must

            options = [pid for pid in players if pid not in taken and allowed(pid)]
            pick = max(options, key=lambda pid: board[t.ext][pid])
            t.roster.append(pick)
            taken.add(pick)


def _position_counts(roster: list[str], players: dict[str, PlayerData]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pid in roster:
        counts[players[pid].position] = counts.get(players[pid].position, 0) + 1
    return counts


# --- in season ------------------------------------------------------------------


def _schedule(rng: random.Random, exts: list[str], weeks: int) -> list[list[tuple[str, str]]]:
    """Round robin (circle method), repeated until the regular season is filled."""
    order = exts[:]
    rng.shuffle(order)
    n = len(order)
    rounds = []
    for _ in range(n - 1):
        pairs = [(order[i], order[n - 1 - i]) for i in range(n // 2)]
        rounds.append(pairs)
        order = [order[0], order[-1], *order[1:-1]]
    return [rounds[w % len(rounds)] for w in range(weeks)]


def _lineup(roster: list[str], players: dict[str, PlayerData], value) -> list[str]:
    lineup = optimal_lineup(
        [
            LineupPlayer(
                player_id=i,
                eligible_slots=tuple(players[pid].eligible_slots or [players[pid].position]),
                value=value(pid),
            )
            for i, pid in enumerate(roster)
        ],
        SLOT_COUNTS,
        respect_injuries=False,
    )
    return [roster[p.player_id] for ps in lineup.values() for p in ps]


def _score(roster, players, week, manager_value) -> float:
    starters = _lineup(roster, players, lambda pid: manager_value(pid, week))
    return round(sum(players[pid].points.get((week, "actual"), 0.0) for pid in starters), 2)


def _projected(roster, players, week) -> float:
    starters = _lineup(roster, players, lambda pid: players[pid].points.get((week, "projected"), 0))
    return round(sum(players[pid].points.get((week, "projected"), 0.0) for pid in starters), 2)


def _record(t: _Team, pf: float, pa: float) -> None:
    t.points_for += pf
    t.points_against += pa
    if pf > pa:
        t.wins += 1
    elif pa > pf:
        t.losses += 1
    else:
        t.ties += 1


def _waivers(rng, teams, players, week, manager_value, start) -> list[TransactionData]:
    """Worst record claims first: the best free agent by recent form, dropping the
    weakest bench player at a position with depth."""
    rostered = {pid for t in teams for pid in t.roster}
    out = []
    for t in sorted(teams, key=lambda t: (t.wins - t.losses, t.points_for)):
        if rng.random() > WAIVER_CLAIM_RATE:
            continue
        starters = set(_lineup(t.roster, players, lambda pid: manager_value(pid, week)))
        counts = _position_counts(t.roster, players)
        droppable = [
            pid
            for pid in t.roster
            if pid not in starters
            and counts[players[pid].position] > DRAFT_MIN[players[pid].position]
        ]
        if not droppable:
            continue
        drop = min(droppable, key=lambda pid: manager_value(pid, week))
        free = [
            pid
            for pid in players
            if pid not in rostered
            and players[pid].position not in LATE_ROUND_ONLY
            and (
                players[pid].position == players[drop].position
                or counts.get(players[pid].position, 0) < DRAFT_MAX[players[pid].position]
            )
        ]
        add = max(free, key=lambda pid: manager_value(pid, week))
        if manager_value(add, week) <= manager_value(drop, week) * 1.1:
            continue
        t.roster[t.roster.index(drop)] = add
        t.claimed.add(add)
        rostered = (rostered - {drop}) | {add}
        when = start + timedelta(weeks=week - 1, days=-1, hours=10 + len(out))
        out.append(
            TransactionData(
                external_id=f"w{week}-{t.ext}",
                type="WAIVER",
                status="EXECUTED",
                team_external_id=t.ext,
                week=week,
                bid_amount=None,
                proposed_at=when - timedelta(hours=30),
                processed_at=when,
                items=[
                    TransactionItemData("ADD", add, None, t.ext),
                    TransactionItemData("DROP", drop, t.ext, None),
                ],
            )
        )
    return out


def _set_lineup(t: _Team, players, week, manager_value) -> list[RosterSlotData]:
    """This week's lineup the way a busy manager sets it: by reputation and recent form,
    without checking the weekly injury report (which is what the dashboard's lineup fixes
    catch). Players on injured reserve do get benched."""
    roster = t.roster

    def value(pid: str) -> float:
        if players[pid].injury_status == "INJURY_RESERVE":
            return 0.0
        return manager_value(pid, week)

    lineup = optimal_lineup(
        [
            LineupPlayer(
                player_id=i,
                eligible_slots=tuple(players[pid].eligible_slots or [players[pid].position]),
                value=value(pid),
            )
            for i, pid in enumerate(roster)
        ],
        SLOT_COUNTS,
        respect_injuries=False,
    )
    slot_of = {roster[p.player_id]: slot for slot, ps in lineup.items() for p in ps}
    out = []
    for pid in roster:
        slot = slot_of.get(pid)
        if slot is None:
            injured = (players[pid].injury_status or "") == "INJURY_RESERVE"
            slot = "IR" if injured and not any(s.slot == "IR" for s in out) else "BE"
        out.append(RosterSlotData(pid, slot, "WAIVER" if pid in t.claimed else "DRAFT"))
    return out


def _season_start(season: int) -> datetime:
    """Thursday of NFL week 1: the Thursday after Labor Day (first Monday of September)."""
    d = datetime(season, 9, 1, tzinfo=UTC)
    while d.weekday() != 0:
        d += timedelta(days=1)
    return d + timedelta(days=3)
