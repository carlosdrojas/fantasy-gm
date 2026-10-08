"""Trade finder and analyzer.

A team's value is its season-long optimal lineup (points per week) plus a small
credit for bench depth. Trades are searched for *your* gain; each also gets an
acceptance estimate from the other manager's point of view (does their lineup
improve, and do they give up more raw value than they get), so you can rank by
gain, by likelihood, or by both. Asks too lopsided to ever be accepted are dropped.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import cache
from itertools import combinations
from typing import Literal

from fantasy_gm.analytics.league import LeagueData, PlayerRow, player_json
from fantasy_gm.analytics.lineup import lineup_total, optimal_lineup

DEPTH_WEIGHT = 0.15  # per-week credit for each of the top bench players
DEPTH_PLAYERS = 3
MIN_MY_GAIN = 0.5  # points/week
MAX_RAW_EDGE = 4.0  # beyond this raw points/game edge in your favor, nobody accepts
CANDIDATES_PER_SIDE = 10
TWO_FOR_TWO_CANDIDATES = 7
UNTRADEABLE_POSITIONS = {"K", "D/ST"}


@dataclass(frozen=True)
class TeamValue:
    total: float
    lineup: float
    depth: float
    starters: frozenset[int]
    dropped: tuple[int, ...]  # players cut to get back under the roster limit


def team_value(rows: Sequence[PlayerRow], slots: dict[str, int], roster_limit: int) -> TeamValue:
    rows = list(rows)
    lineup = optimal_lineup([r.lineup_player() for r in rows], slots, respect_injuries=False)
    starters = frozenset(p.player_id for ps in lineup.values() for p in ps)
    bench = sorted(
        (r for r in rows if r.player.id not in starters and r.slot != "IR"),
        key=lambda r: r.value.per_game,
    )
    # Receiving more players than you send means cutting your weakest bench players.
    active = [r for r in rows if r.slot != "IR"]
    excess = max(0, len(active) - roster_limit)
    dropped = tuple(r.player.id for r in bench[:excess])
    bench = bench[excess:]
    depth = sum(r.value.per_game for r in bench[-DEPTH_PLAYERS:]) * DEPTH_WEIGHT
    lt = lineup_total(lineup)
    return TeamValue(round(lt + depth, 2), lt, round(depth, 2), starters, dropped)


@dataclass
class _Side:
    team_id: int
    rows: list[PlayerRow]
    limit: int

    def value(
        self, slots: dict[str, int], out: Iterable[int], incoming: Sequence[PlayerRow]
    ) -> TeamValue:
        out_ids = set(out)
        new_rows = [r for r in self.rows if r.player.id not in out_ids]
        new_rows += [
            PlayerRow(r.player, r.value, slot="BE", team_id=self.team_id) for r in incoming
        ]
        return team_value(new_rows, slots, self.limit)


def _roster_limit(rows: list[PlayerRow]) -> int:
    return len([r for r in rows if r.slot != "IR"])


def _candidates(rows: list[PlayerRow], n: int, *, tradeable_now: bool = False) -> list[PlayerRow]:
    pool = [
        r
        for r in rows
        if r.slot != "IR"
        and r.player.position not in UNTRADEABLE_POSITIONS
        and not (tradeable_now and r.locked)
    ]
    return sorted(pool, key=lambda r: r.value.per_game, reverse=True)[:n]


def evaluate_trade(
    data: LeagueData, team_id: int, partner_id: int, give: Sequence[int], get: Sequence[int]
) -> dict:
    """Score a specific trade from ``team_id``'s point of view."""
    mine = data.rosters.get(team_id, [])
    theirs = data.rosters.get(partner_id, [])
    my_by_id = {r.player.id: r for r in mine}
    their_by_id = {r.player.id: r for r in theirs}
    missing = [p for p in give if p not in my_by_id] + [p for p in get if p not in their_by_id]
    if missing:
        raise ValueError(f"Players not on the expected rosters: {missing}")
    slots = data.slot_counts
    me = _Side(team_id, mine, _roster_limit(mine))
    them = _Side(partner_id, theirs, _roster_limit(theirs))
    my_before, their_before = me.value(slots, [], []), them.value(slots, [], [])
    my_after = me.value(slots, give, [their_by_id[p] for p in get])
    their_after = them.value(slots, get, [my_by_id[p] for p in give])
    return _trade_json(
        data,
        partner_id,
        [my_by_id[p] for p in give],
        [their_by_id[p] for p in get],
        my_before,
        my_after,
        their_before,
        their_after,
    )


def _trade_json(
    data: LeagueData,
    partner_id: int,
    give: list[PlayerRow],
    get: list[PlayerRow],
    my_before: TeamValue,
    my_after: TeamValue,
    their_before: TeamValue,
    their_after: TeamValue,
) -> dict:
    my_gain = round(my_after.total - my_before.total, 2)
    their_gain = round(their_after.total - their_before.total, 2)
    raw_edge = round(sum(r.value.per_game for r in get) - sum(r.value.per_game for r in give), 2)
    all_rows = {r.player.id: r for rows in data.rosters.values() for r in rows}
    return {
        "partner_team_id": partner_id,
        "give": [player_json(r) for r in give],
        "get": [player_json(r) for r in get],
        "my_gain": my_gain,
        "their_gain": their_gain,
        "my_lineup_gain": round(my_after.lineup - my_before.lineup, 2),
        "their_lineup_gain": round(their_after.lineup - their_before.lineup, 2),
        "raw_value_edge": raw_edge,  # >0: you receive more raw points/game than you send
        "my_drops": [player_json(all_rows[p]) for p in my_after.dropped if p in all_rows],
        "their_drops": [player_json(all_rows[p]) for p in their_after.dropped if p in all_rows],
        "acceptance": acceptance(their_gain, raw_edge),
        "verdict": _verdict(my_gain, their_gain),
        # False when a player involved has already played this week (locked on ESPN).
        "tradeable_now": not any(r.locked for r in [*give, *get]),
    }


def acceptance(their_gain: float, raw_edge: float) -> float:
    """Rough 0-1 chance the other manager says yes.

    Managers judge trades mostly by raw player value (what they see in rankings) and
    partly by lineup fit. Both are in points per week.
    """
    x = 0.4 + 0.6 * their_gain - 0.9 * max(raw_edge, 0) + 0.3 * max(-raw_edge, 0)
    return round(1 / (1 + math.exp(-x)), 2)


def _verdict(my_gain: float, their_gain: float) -> str:
    if my_gain <= 0:
        return "bad_for_you"
    if their_gain > 0.25:
        return "win_win"
    if their_gain >= -0.25:
        return "neutral_for_them"
    return "they_lose"


SortMode = Literal["balanced", "gain", "likely"]


def _sort_key(mode: SortMode):
    if mode == "gain":
        return lambda t: t["my_gain"]
    if mode == "likely":
        return lambda t: t["acceptance"] + t["my_gain"] / 1000  # gain breaks ties
    return lambda t: t["my_gain"] * t["acceptance"]


def _improvers(
    side_rows: list[PlayerRow], incoming: list[PlayerRow], starters: frozenset[int]
) -> list[PlayerRow]:
    """Incoming players who beat at least one current starter they could replace."""
    starter_rows = [r for r in side_rows if r.player.id in starters]
    out = []
    for r in incoming:
        slots = set(r.player.eligible_slots or [r.player.position])
        weakest = [
            s.value.per_game
            for s in starter_rows
            if slots & set(s.player.eligible_slots or [s.player.position])
        ]
        if not weakest or r.value.per_game > min(weakest):
            out.append(r)
    return out


def find_trades(
    data: LeagueData,
    team_id: int,
    partner_id: int | None = None,
    limit: int = 20,
    sort: SortMode = "balanced",
    *,
    tradeable_now: bool = False,
) -> list[dict]:
    """Search 1-for-1, 2-for-1, 1-for-2 and 2-for-2 trades with every other team.

    ``tradeable_now`` leaves out players whose game this week has started (ESPN has
    locked them), so every trade returned can be made right away.
    """
    mine = data.rosters.get(team_id, [])
    if not mine:
        return []
    slots = data.slot_counts
    me = _Side(team_id, mine, _roster_limit(mine))

    @cache
    def my_value(out: frozenset[int], incoming: frozenset[int]) -> TeamValue:
        return me.value(slots, out, [all_rows[p] for p in incoming])

    all_rows = {r.player.id: r for rows in data.rosters.values() for r in rows}
    my_before = my_value(frozenset(), frozenset())
    my_cands = _candidates(mine, CANDIDATES_PER_SIDE, tradeable_now=tradeable_now)

    results: list[dict] = []
    partners = [partner_id] if partner_id else [t for t in data.teams if t != team_id]
    for pid in partners:
        theirs = data.rosters.get(pid, [])
        if not theirs:
            continue
        them = _Side(pid, theirs, _roster_limit(theirs))
        their_before = them.value(slots, [], [])
        # Only players who'd crack my lineup are worth asking for; only mine who'd crack theirs are worth offering.
        their_cands = _improvers(
            mine,
            _candidates(theirs, CANDIDATES_PER_SIDE, tradeable_now=tradeable_now),
            my_before.starters,
        )
        offer_cands = _improvers(theirs, my_cands, their_before.starters)
        if not their_cands or not offer_cands:
            continue

        shapes: list[tuple[tuple[PlayerRow, ...], tuple[PlayerRow, ...]]] = []
        shapes += [((g,), (r,)) for g in offer_cands for r in their_cands]
        shapes += [(g, (r,)) for g in combinations(offer_cands, 2) for r in their_cands]
        shapes += [((g,), r) for g in offer_cands for r in combinations(their_cands, 2)]
        shapes += [
            (g, r)
            for g in combinations(offer_cands[:TWO_FOR_TWO_CANDIDATES], 2)
            for r in combinations(their_cands[:TWO_FOR_TWO_CANDIDATES], 2)
        ]

        for give, get in shapes:
            my_after = my_value(
                frozenset(r.player.id for r in give), frozenset(r.player.id for r in get)
            )
            if my_after.total - my_before.total < MIN_MY_GAIN:
                continue
            raw_edge = sum(r.value.per_game for r in get) - sum(r.value.per_game for r in give)
            if raw_edge > MAX_RAW_EDGE:
                continue
            their_after = them.value(slots, [r.player.id for r in get], give)
            results.append(
                _trade_json(
                    data, pid, list(give), list(get), my_before, my_after, their_before, their_after
                )
            )

    results.sort(key=_sort_key(sort), reverse=True)
    return _dedupe(results, _sort_key(sort))[:limit]


def _dedupe(trades: list[dict], key) -> list[dict]:
    """Drop bigger packages that don't beat a simpler trade already containing their core."""
    kept: list[dict] = []
    for t in trades:
        ids = {p["id"] for p in t["give"]} | {p["id"] for p in t["get"]}
        dominated = any(
            k["partner_team_id"] == t["partner_team_id"]
            and ({p["id"] for p in k["give"]} | {p["id"] for p in k["get"]}) < ids
            and key(k) >= key(t) - 0.25
            for k in kept
        )
        if not dominated:
            kept.append(t)
    return kept
