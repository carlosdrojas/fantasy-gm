"""Refresh the demo league's player pool (src/fantasy_gm/demo/pool.json) from ESPN.

Dev-only: needs ESPN cookies in backend/.env and a league you can read. Player names,
teams and weekly fantasy points are public NFL data; nothing league-specific is kept.

    .venv/bin/python scripts/export_demo_pool.py <espn_league_id> [--season 2026] [--week 5]

``--week`` is the demo's current week: weeks before it are completed (actual points),
and it carries ESPN's projection for that week.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fantasy_gm.config import get_settings
from fantasy_gm.domain import PlayerData
from fantasy_gm.espn import parse
from fantasy_gm.espn.client import EspnClient
from fantasy_gm.espn.constants import POSITION_FILTER_SLOTS
from fantasy_gm.sync import make_espn_client

OUT = Path(__file__).resolve().parents[1] / "src" / "fantasy_gm" / "demo" / "pool.json"
PER_POSITION = {"QB": 32, "RB": 70, "WR": 90, "TE": 32, "K": 20, "D/ST": 20}
CHUNK = 100


def fetch(c: EspnClient, league: str, season: int, week: int) -> list[PlayerData]:
    """Top players by ownership at each position, with season and weekly points."""
    players: dict[str, PlayerData] = {}
    for pos, slot in POSITION_FILTER_SLOTS.items():
        f = {
            "players": {
                "filterSlotIds": {"value": [slot]},
                "limit": PER_POSITION[pos],
                "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
                "filterStatsForTopScoringPeriodIds": {
                    "value": 1,
                    "additionalValue": [f"00{season}", f"10{season}", f"11{season}{week}"],
                },
            }
        }
        data = c.league(league, season, ["kona_player_info"], scoring_period=week, fantasy_filter=f)
        for e in data.get("players") or []:
            if (p := parse.parse_player(e, season)) and p.position == pos:
                players[p.external_id] = p

    # Weekly actuals: ESPN returns a player's last N games, so ask for a few more than
    # the weeks we need (older seasons are filtered out by parse_player).
    ids = [int(i) for i in players if i.lstrip("-").isdigit()]
    for i in range(0, len(ids), CHUNK):
        f = {
            "players": {
                "filterIds": {"value": ids[i : i + CHUNK]},
                "filterStatsForTopScoringPeriodIds": {"value": week + 2, "additionalValue": []},
            }
        }
        data = c.league(league, season, ["kona_playercard"], scoring_period=week, fantasy_filter=f)
        for e in data.get("players") or []:
            p = parse.parse_player(e, season)
            if p and p.external_id in players:
                players[p.external_id].points.update(
                    (k, v) for k, v in p.points.items() if k[1] == "actual" and 0 < k[0] < week
                )
    return list(players.values())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("league_id")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--week", type=int, default=5)
    args = ap.parse_args()

    with make_espn_client(get_settings()) as c:
        players = fetch(c, args.league_id, args.season, args.week)

    out = {
        "season": args.season,
        "current_week": args.week,
        "players": [
            {
                "id": p.external_id,
                "name": p.full_name,
                "position": p.position,
                "pro_team": p.pro_team,
                "injury_status": p.injury_status,
                "eligible_slots": p.eligible_slots,
                "percent_owned": p.percent_owned,
                # "<week>:<kind>" -> points; week 0 is the season total / projection
                "points": {f"{w}:{k}": v for (w, k), v in sorted(p.points.items())},
            }
            for p in sorted(players, key=lambda p: (p.position, p.external_id))
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(f"Wrote {len(players)} players to {OUT}")


if __name__ == "__main__":
    main()
