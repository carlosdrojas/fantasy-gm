"""Monte Carlo season simulation: playoff, bye, #1 seed and title odds.

Each team's weekly score is modeled as Normal(mean, sd):
- mean blends points scored so far with current roster strength (the optimal
  lineup's expected points), rescaled so the two are on the same scale;
- sd is the league's pooled week-to-week variation.
The current week uses ESPN's live projections when available. Playoffs are a
single-elimination bracket; top seeds get byes when the field isn't a power of two.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

import numpy as np

from fantasy_gm.analytics.league import LeagueData, completed_results, roster_strength

DEFAULT_SD = 25.0
MIN_SD, MAX_SD = 12.0, 45.0
LIVE_WEEK_SD = 14.0  # less uncertainty once a week's games are underway
DEFAULT_SIMS = 5000
HISTORY_PRIOR_GAMES = 3  # history weight = games / (games + prior)


@dataclass
class TeamModel:
    team_id: int
    mean: float
    wins: float
    points_for: float


def team_models(
    data: LeagueData, strength_override: dict[int, float] | None = None
) -> tuple[dict[int, TeamModel], float]:
    results = completed_results(data.matchups)
    by_team: dict[int, list[float]] = {t: [] for t in data.teams}
    for r in results:
        by_team.setdefault(r.team_id, []).append(r.points)

    strength = {t: roster_strength(data, t) for t in data.teams}
    if strength_override:
        strength.update(strength_override)

    all_scores = [p for ps in by_team.values() for p in ps]
    mean_strength = statistics.fmean(strength.values()) if strength else 0.0
    # Roster strength and actual scoring can sit on different scales (projection bias);
    # rescale strength to the league's actual scoring once there's enough history.
    scale = 1.0
    if len(all_scores) >= 2 * len(data.teams) and mean_strength > 0:
        scale = statistics.fmean(all_scores) / mean_strength

    residuals = []
    models = {}
    for tid, team in data.teams.items():
        hist = by_team.get(tid, [])
        s = strength[tid] * scale
        if hist:
            w = len(hist) / (len(hist) + HISTORY_PRIOR_GAMES)
            mean = w * statistics.fmean(hist) + (1 - w) * s
            residuals += [p - statistics.fmean(hist) for p in hist]
        else:
            mean = s
        models[tid] = TeamModel(tid, mean, team.wins + 0.5 * team.ties, team.points_for)

    sd = DEFAULT_SD
    if len(residuals) >= 10:
        sd = min(max(statistics.pstdev(residuals), MIN_SD), MAX_SD)
    return models, sd


def _bracket_champions(
    seeds: np.ndarray, means: np.ndarray, sd: float, rng: np.random.Generator
) -> np.ndarray:
    """seeds: (n_sims, n_playoff) team indices in seed order. Returns champion index per sim."""
    current = seeds.copy()
    while current.shape[1] > 1:
        n = current.shape[1]
        byes = 2 ** math.ceil(math.log2(n)) - n
        bye_teams = current[:, :byes]
        playing = current[:, byes:]
        k = playing.shape[1] // 2
        high, low = playing[:, :k], playing[:, ::-1][:, :k]
        s_high = rng.normal(means[high], sd)
        s_low = rng.normal(means[low], sd)
        winners = np.where(s_high >= s_low, high, low)
        current = np.concatenate([bye_teams, winners], axis=1)
    return current[:, 0]


def simulate(
    data: LeagueData,
    *,
    n_sims: int = DEFAULT_SIMS,
    strength_override: dict[int, float] | None = None,
    seed: int | None = None,
) -> dict[int, dict]:
    team_ids = list(data.teams)
    if not team_ids:
        return {}
    idx = {t: i for i, t in enumerate(team_ids)}
    models, sd = team_models(data, strength_override)
    means = np.array([models[t].mean for t in team_ids])
    settings = data.league.settings or {}
    playoff_teams = min(settings.get("playoff_team_count") or 4, len(team_ids))
    last_week = data.league.final_regular_week or settings.get("regular_season_weeks") or 99
    rng = np.random.default_rng(
        seed if seed is not None else data.league.id * 1000 + (data.league.current_week or 0)
    )

    wins = np.tile(np.array([models[t].wins for t in team_ids]), (n_sims, 1))
    pf = np.tile(np.array([models[t].points_for for t in team_ids]), (n_sims, 1))

    remaining = [
        m
        for m in data.matchups
        if m.winner == "UNDECIDED" and not m.is_playoff and m.week <= last_week and m.away_team_id
    ]
    for m in remaining:
        h, a = idx[m.home_team_id], idx[m.away_team_id]  # type: ignore[index]
        live = (
            m.home_projected is not None
            and m.away_projected is not None
            and ((m.home_points or 0) > 0 or (m.away_points or 0) > 0)
        )
        if live:
            hs = rng.normal(m.home_projected, LIVE_WEEK_SD, n_sims)
            as_ = rng.normal(m.away_projected, LIVE_WEEK_SD, n_sims)
        else:
            hs = rng.normal(means[h], sd, n_sims)
            as_ = rng.normal(means[a], sd, n_sims)
        wins[:, h] += (hs > as_) + 0.5 * (hs == as_)
        wins[:, a] += (as_ > hs) + 0.5 * (hs == as_)
        pf[:, h] += hs
        pf[:, a] += as_

    # Seed by wins, then points for (lexsort's last key is primary).
    order = np.lexsort((-pf, -wins), axis=1)  # (n_sims, n_teams) team indices best-first
    playoff = order[:, :playoff_teams]
    byes = 2 ** math.ceil(math.log2(playoff_teams)) - playoff_teams if playoff_teams > 1 else 0
    champs = _bracket_champions(playoff, means, sd, rng) if playoff_teams > 1 else playoff[:, 0]

    out = {}
    for t, i in idx.items():
        seed_pos = np.argmax(order == i, axis=1)  # 0-based seed per sim
        out[t] = {
            "playoff_pct": round(100 * float(np.mean(seed_pos < playoff_teams)), 1),
            "bye_pct": round(100 * float(np.mean(seed_pos < byes)), 1) if byes else None,
            "first_seed_pct": round(100 * float(np.mean(seed_pos == 0)), 1),
            "champion_pct": round(100 * float(np.mean(champs == i)), 1),
            "avg_wins": round(float(wins[:, i].mean()), 1),
            "avg_seed": round(float(seed_pos.mean()) + 1, 1),
            "weekly_mean": round(float(means[i]), 1),
        }
    return out


def simulation_meta(data: LeagueData) -> dict:
    settings = data.league.settings or {}
    last_week = data.league.final_regular_week or settings.get("regular_season_weeks")
    remaining_weeks = sorted(
        {
            m.week
            for m in data.matchups
            if m.winner == "UNDECIDED"
            and not m.is_playoff
            and (last_week is None or m.week <= last_week)
        }
    )
    _, sd = team_models(data)
    return {
        "sims": DEFAULT_SIMS,
        "playoff_teams": settings.get("playoff_team_count"),
        "remaining_weeks": remaining_weeks,
        "weekly_sd": round(sd, 1),
    }
