"""Per-player weekly value estimate: blends projection with recent production."""

from __future__ import annotations

from dataclasses import dataclass

SEASON_GAMES = 17
RECENT_WEEKS = 4
PROJECTION_WEIGHT = 0.6  # vs. recent actual average


@dataclass(frozen=True)
class PlayerValue:
    per_game: float  # blended expected points per game
    projected_per_game: float | None
    recent_avg: float | None
    this_week_projection: float | None
    this_week_actual: float | None  # live during the week, final after
    trend: float | None  # recent average minus earlier average (positive = heating up)


def player_value(points: dict[tuple[int, str], float], current_week: int | None) -> PlayerValue:
    """``points`` maps (week, kind) -> points; week 0 is the season total."""
    season_proj = points.get((0, "projected"))
    proj_pg = season_proj / SEASON_GAMES if season_proj else None

    completed = sorted(
        w
        for (w, k) in points
        if k == "actual" and w > 0 and (current_week is None or w < current_week)
    )
    # A zero usually means a bye or DNP; leave it out of the averages.
    played = [(w, points[(w, "actual")]) for w in completed if points[(w, "actual")] != 0]
    recent = [p for _, p in played[-RECENT_WEEKS:]]
    earlier = [p for _, p in played[:-RECENT_WEEKS]]
    recent_avg = sum(recent) / len(recent) if recent else None
    trend = None
    if recent and earlier:
        trend = round(recent_avg - sum(earlier) / len(earlier), 2)  # type: ignore[operator]
    elif len(played) >= 2:
        half = len(played) // 2
        first, last = [p for _, p in played[:half]], [p for _, p in played[half:]]
        trend = round(sum(last) / len(last) - sum(first) / len(first), 2)

    if proj_pg is not None and recent_avg is not None:
        # Trust recent production more as the sample grows.
        w = PROJECTION_WEIGHT if len(recent) >= 3 else 0.8
        per_game = w * proj_pg + (1 - w) * recent_avg
    else:
        per_game = proj_pg if proj_pg is not None else (recent_avg or 0.0)

    this_week = points.get((current_week, "projected")) if current_week else None
    this_week_actual = points.get((current_week, "actual")) if current_week else None
    return PlayerValue(
        per_game=round(per_game, 2),
        projected_per_game=round(proj_pg, 2) if proj_pg is not None else None,
        recent_avg=round(recent_avg, 2) if recent_avg is not None else None,
        this_week_projection=this_week,
        this_week_actual=this_week_actual,
        trend=trend,
    )
