"""Standings-beyond-the-record: all-play, expected wins, luck, power score."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GameResult:
    week: int
    team_id: int
    points: float
    won: bool | None  # None for ties


@dataclass
class TeamPower:
    team_id: int
    all_play_wins: int = 0
    all_play_losses: int = 0
    all_play_ties: int = 0
    expected_wins: float = 0.0
    actual_wins: float = 0.0
    weekly_points: dict[int, float] = field(default_factory=dict)

    @property
    def all_play_pct(self) -> float:
        games = self.all_play_wins + self.all_play_losses + self.all_play_ties
        return (self.all_play_wins + 0.5 * self.all_play_ties) / games if games else 0.0

    @property
    def luck(self) -> float:
        """Actual wins minus expected wins. Positive = lucky."""
        return round(self.actual_wins - self.expected_wins, 2)


def all_play(results: list[GameResult]) -> dict[int, TeamPower]:
    """Every team vs every other team, every completed week."""
    by_week: dict[int, list[GameResult]] = defaultdict(list)
    for r in results:
        by_week[r.week].append(r)

    power: dict[int, TeamPower] = {}
    for week, games in by_week.items():
        n = len(games)
        for g in games:
            tp = power.setdefault(g.team_id, TeamPower(g.team_id))
            tp.weekly_points[week] = g.points
            tp.actual_wins += 1.0 if g.won else 0.5 if g.won is None else 0.0
            if n < 2:
                continue
            beat = sum(1 for o in games if o.team_id != g.team_id and o.points < g.points)
            tied = sum(1 for o in games if o.team_id != g.team_id and o.points == g.points)
            lost = n - 1 - beat - tied
            tp.all_play_wins += beat
            tp.all_play_ties += tied
            tp.all_play_losses += lost
            tp.expected_wins += (beat + 0.5 * tied) / (n - 1)
    for tp in power.values():
        tp.expected_wins = round(tp.expected_wins, 2)
    return power


def _normalize(values: dict[int, float]) -> dict[int, float]:
    """Min-max scale to [0, 1]; all-equal inputs map to 0.5."""
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return {k: 0.5 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


POWER_WEIGHTS = {"all_play": 0.45, "recent_form": 0.25, "roster_strength": 0.30}
RECENT_WEEKS = 3


def power_scores(
    power: dict[int, TeamPower], roster_strength: dict[int, float]
) -> dict[int, dict[str, float]]:
    """Composite 0-100 score from season results, recent scoring, and roster strength.

    Early in the season (no completed weeks) it is driven entirely by roster strength.
    """
    team_ids = set(power) | set(roster_strength)
    all_play_pct = {t: power[t].all_play_pct if t in power else 0.0 for t in team_ids}
    recent: dict[int, float] = {}
    for t in team_ids:
        pts = power[t].weekly_points if t in power else {}
        last = [pts[w] for w in sorted(pts)[-RECENT_WEEKS:]]
        recent[t] = sum(last) / len(last) if last else 0.0

    has_results = any(tp.weekly_points for tp in power.values())
    weights = (
        POWER_WEIGHTS if has_results else {"all_play": 0, "recent_form": 0, "roster_strength": 1}
    )
    components = {
        "all_play": _normalize(all_play_pct),
        "recent_form": _normalize(recent),
        "roster_strength": _normalize({t: roster_strength.get(t, 0.0) for t in team_ids}),
    }
    out: dict[int, dict[str, float]] = {}
    for t in team_ids:
        parts = {k: components[k][t] for k in components}
        score = sum(weights[k] * parts[k] for k in parts)
        out[t] = {
            "score": round(100 * score, 1),
            **{k: round(100 * v, 1) for k, v in parts.items()},
        }
    return out
