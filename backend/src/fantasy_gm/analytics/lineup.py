"""Optimal lineup: assign players to starting slots maximizing total value.

Solved exactly as an assignment problem (scipy's linear_sum_assignment), so
FLEX/superflex slots and multi-eligible players are handled correctly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment

NON_STARTING = {"BE", "IR"}
UNAVAILABLE_STATUSES = {"OUT", "INJURY_RESERVE", "SUSPENSION", "DOUBTFUL"}


@dataclass(frozen=True)
class LineupPlayer:
    player_id: int
    eligible_slots: tuple[str, ...]
    value: float
    injury_status: str | None = None
    on_ir: bool = False


def optimal_lineup(
    players: Sequence[LineupPlayer],
    slot_counts: dict[str, int],
    *,
    respect_injuries: bool = True,
) -> dict[str, list[LineupPlayer]]:
    """Return {slot: [players]} for starting slots. Unfillable slots stay short.

    Players on IR never start. With ``respect_injuries`` (a specific week), players
    ruled out/doubtful don't either; turn it off for season-long strength.
    """
    slots = [s for s, n in sorted(slot_counts.items()) if s not in NON_STARTING for _ in range(n)]
    result: dict[str, list[LineupPlayer]] = {s: [] for s in slot_counts if s not in NON_STARTING}
    pool = [
        p
        for p in players
        if not p.on_ir
        and not (respect_injuries and (p.injury_status or "").upper() in UNAVAILABLE_STATUSES)
    ]
    if not slots or not pool:
        return result

    # Rows: slot instances; columns: players, then one "leave empty" column per slot.
    big = 1e6
    cost = np.full((len(slots), len(pool) + len(slots)), 0.0)
    for i, slot in enumerate(slots):
        for j, p in enumerate(pool):
            cost[i, j] = -max(p.value, 0.0) if slot in p.eligible_slots else big
    rows, cols = linear_sum_assignment(cost)
    for i, j in zip(rows, cols, strict=True):
        if j < len(pool) and cost[i, j] < 0:
            result[slots[i]].append(pool[j])
    return result


def lineup_total(lineup: dict[str, list[LineupPlayer]]) -> float:
    return round(sum(p.value for ps in lineup.values() for p in ps), 2)
