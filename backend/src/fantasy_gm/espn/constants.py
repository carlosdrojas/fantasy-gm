"""ESPN numeric id -> name tables (facts about ESPN's unofficial v3 API)."""

from __future__ import annotations

POSITIONS: dict[int, str] = {
    1: "QB",
    2: "RB",
    3: "WR",
    4: "TE",
    5: "K",
    7: "P",
    9: "DT",
    10: "DE",
    11: "LB",
    12: "CB",
    13: "S",
    14: "HC",
    16: "D/ST",
}

LINEUP_SLOTS: dict[int, str] = {
    0: "QB",
    1: "TQB",
    2: "RB",
    3: "RB/WR",
    4: "WR",
    5: "WR/TE",
    6: "TE",
    7: "OP",
    8: "DT",
    9: "DE",
    10: "LB",
    11: "DL",
    12: "CB",
    13: "S",
    14: "DB",
    15: "DP",
    16: "D/ST",
    17: "K",
    18: "P",
    19: "HC",
    20: "BE",
    21: "IR",
    23: "FLEX",
    24: "EDR",
    25: "RB/WR/TE",
}
BENCH_SLOT = 20
IR_SLOT = 21

PRO_TEAMS: dict[int, str] = {
    0: "FA",
    1: "ATL",
    2: "BUF",
    3: "CHI",
    4: "CIN",
    5: "CLE",
    6: "DAL",
    7: "DEN",
    8: "DET",
    9: "GB",
    10: "TEN",
    11: "IND",
    12: "KC",
    13: "LV",
    14: "LAR",
    15: "MIA",
    16: "MIN",
    17: "NE",
    18: "NO",
    19: "NYG",
    20: "NYJ",
    21: "PHI",
    22: "ARI",
    23: "PIT",
    24: "LAC",
    25: "SF",
    26: "SEA",
    27: "TB",
    28: "WSH",
    29: "CAR",
    30: "JAX",
    33: "BAL",
    34: "HOU",
}

# player.stats[].statSourceId / statSplitTypeId
STAT_SOURCE_ACTUAL = 0
STAT_SOURCE_PROJECTED = 1
SPLIT_SEASON = 0
SPLIT_WEEK = 1

# ESPN's filterSlotIds value for each fantasy position (free agent queries).
POSITION_FILTER_SLOTS: dict[str, int] = {"QB": 0, "RB": 2, "WR": 4, "TE": 6, "K": 17, "D/ST": 16}


def lookup(table: dict[int, str], key: object, default: str = "UNK") -> str:
    try:
        return table.get(int(key), f"{default}_{key}")  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
