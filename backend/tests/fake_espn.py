"""A synthetic 4-team ESPN league served through httpx.MockTransport.

Shapes follow ESPN's v3 API: week 4 is current, weeks 1-3 are final.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

SEASON = 2026
LEAGUE_ID = "4242"
CURRENT_WEEK = 4
MY_SWID = "{11111111-2222-3333-4444-555555555555}"

# eligible slot ids by position
ELIGIBLE = {
    1: [0, 7, 20, 21],
    2: [2, 3, 23, 7, 20, 21],
    3: [4, 3, 5, 23, 7, 20, 21],
    4: [6, 5, 23, 7, 20, 21],
    5: [17, 20, 21],
    16: [16, 20, 21],
}


def player(
    pid: int,
    name: str,
    pos: int,
    pro: int,
    ppg: float,
    *,
    weeks: dict[int, float] | None = None,
    injury: str = "ACTIVE",
    owned: float = 50.0,
    change: float = 0.0,
) -> dict[str, Any]:
    weeks = weeks if weeks is not None else {1: ppg, 2: ppg, 3: ppg}
    stats = [
        {
            "seasonId": SEASON,
            "scoringPeriodId": 0,
            "statSourceId": 1,
            "statSplitTypeId": 0,
            "appliedTotal": ppg * 17,
        },
        {
            "seasonId": SEASON,
            "scoringPeriodId": 0,
            "statSourceId": 0,
            "statSplitTypeId": 0,
            "appliedTotal": sum(weeks.values()),
        },
        {
            "seasonId": SEASON,
            "scoringPeriodId": CURRENT_WEEK,
            "statSourceId": 1,
            "statSplitTypeId": 1,
            "appliedTotal": ppg,
        },
        {
            "seasonId": SEASON - 1,
            "scoringPeriodId": 0,
            "statSourceId": 0,
            "statSplitTypeId": 0,
            "appliedTotal": 999,
        },
    ]
    stats += [
        {
            "seasonId": SEASON,
            "scoringPeriodId": w,
            "statSourceId": 0,
            "statSplitTypeId": 1,
            "appliedTotal": pts,
        }
        for w, pts in weeks.items()
    ]
    return {
        "id": pid,
        "fullName": name,
        "defaultPositionId": pos,
        "proTeamId": pro,
        "injuryStatus": injury,
        "eligibleSlots": ELIGIBLE[pos],
        "ownership": {"percentOwned": owned, "percentChange": change},
        "stats": stats,
    }


def _roster(players: list[tuple[int, dict]]) -> dict:
    return {
        "entries": [
            {
                "playerId": p["id"],
                "lineupSlotId": slot,
                "acquisitionType": "DRAFT",
                "playerPoolEntry": {"player": p},
            }
            for slot, p in players
        ]
    }


def build_league() -> dict[str, Any]:
    pid = iter(range(1000, 2000))

    def team_roster(strength: float, weak_rb: bool = False) -> list[tuple[int, dict]]:
        rb = strength * (0.4 if weak_rb else 1.0)
        return [
            (0, player(next(pid), "QB", 1, 2, 20 * strength)),
            (2, player(next(pid), "RB1", 2, 6, 15 * rb)),
            (2, player(next(pid), "RB2", 2, 7, 12 * rb)),
            (4, player(next(pid), "WR1", 3, 8, 14 * strength)),
            (4, player(next(pid), "WR2", 3, 9, 11 * strength)),
            (6, player(next(pid), "TE", 4, 10, 8 * strength)),
            (23, player(next(pid), "FLEX WR", 3, 11, 9 * strength)),
            (16, player(next(pid), "DST", 16, 16, 7.0)),
            (17, player(next(pid), "K", 5, 12, 8.0)),
            (20, player(next(pid), "Bench WR", 3, 13, 13 * strength)),  # better than FLEX starter
            (20, player(next(pid), "Bench RB", 2, 14, 4 * rb)),
            (21, player(next(pid), "IR RB", 2, 15, 16.0, injury="INJURY_RESERVE")),
        ]

    teams = []
    for tid, (name, strength, owner, weak_rb) in enumerate(
        [
            ("Mine", 1.0, MY_SWID, True),
            ("Juggernaut", 1.4, "{B}", False),
            ("Middling", 1.0, "{C}", False),
            ("Tankers", 0.6, "{D}", False),
        ],
        start=1,
    ):
        teams.append(
            {
                "id": tid,
                "name": name,
                "abbrev": name[:3].upper(),
                "owners": [owner],
                "playoffSeed": tid,
                "waiverRank": 5 - tid,
                "transactionCounter": {"acquisitionBudgetSpent": 10 * tid},
                "record": {
                    "overall": {
                        "wins": 3 - (tid - 1) % 4,
                        "losses": (tid - 1) % 4,
                        "ties": 0,
                        "pointsFor": 300.0 / tid,
                        "pointsAgainst": 250.0,
                    }
                },
                "roster": _roster(team_roster(strength, weak_rb)),
            }
        )

    # Weeks 1-3: 1v2, 3v4 / 1v3, 2v4 / 1v4, 2v3. Scores are fixed per team per week.
    scores = {
        1: {1: 110, 2: 140, 3: 100, 4: 90},
        2: {1: 95, 2: 150, 3: 120, 4: 80},
        3: {1: 130, 2: 125, 3: 105, 4: 70},
    }
    pairs = {1: [(1, 2), (3, 4)], 2: [(1, 3), (2, 4)], 3: [(1, 4), (2, 3)], 4: [(1, 2), (3, 4)]}
    schedule = []
    mid = iter(range(1, 100))
    for week, games in pairs.items():
        for home, away in games:
            if week < CURRENT_WEEK:
                h, a = scores[week][home], scores[week][away]
                winner = "HOME" if h > a else "AWAY" if a > h else "TIE"
                schedule.append(
                    {
                        "id": next(mid),
                        "matchupPeriodId": week,
                        "winner": winner,
                        "playoffTierType": "NONE",
                        "home": {"teamId": home, "totalPoints": h},
                        "away": {"teamId": away, "totalPoints": a},
                    }
                )
            else:
                schedule.append(
                    {
                        "id": next(mid),
                        "matchupPeriodId": week,
                        "winner": "UNDECIDED",
                        "playoffTierType": "NONE",
                        "home": {
                            "teamId": home,
                            "totalPoints": 0,
                            "totalPointsLive": 42.5,
                            "totalProjectedPointsLive": 120.1,
                        },
                        "away": {
                            "teamId": away,
                            "totalPoints": 0,
                            "totalPointsLive": 30.0,
                            "totalProjectedPointsLive": 101.9,
                        },
                    }
                )

    free_agents = [
        {
            "id": 5001,
            "player": player(
                5001,
                "Waiver Stud RB",
                2,
                17,
                14.0,
                weeks={1: 5, 2: 12, 3: 20},
                owned=30,
                change=12.5,
            ),
        },
        {"id": 5002, "player": player(5002, "Scrub TE", 4, 18, 1.0, owned=0.5)},
        {"id": 5003, "player": player(5003, "Hurt WR", 3, 19, 10.0, injury="OUT", owned=20)},
    ]
    return {
        "teams": teams,
        "schedule": schedule,
        "free_agents": free_agents,
        "settings": {
            "name": "Test League",
            "size": 4,
            "rosterSettings": {
                "lineupSlotCounts": {
                    "0": 1,
                    "2": 2,
                    "4": 2,
                    "6": 1,
                    "23": 1,
                    "16": 1,
                    "17": 1,
                    "20": 7,
                    "21": 1,
                    "7": 0,
                }
            },
            "scheduleSettings": {"matchupPeriodCount": 14, "playoffTeamCount": 2},
            "scoringSettings": {
                "scoringType": "H2H_POINTS",
                "scoringItems": [{"statId": 53, "points": 1.0}],
            },
            "acquisitionSettings": {"isUsingAcquisitionBudget": True, "acquisitionBudget": 100},
        },
        "members": [
            {"id": MY_SWID, "firstName": "Carlos", "lastName": "R"},
            {"id": "{B}", "displayName": "bee"},
        ],
        "transactions": {
            3: [
                {
                    "id": "tx-waiver",
                    "type": "WAIVER",
                    "status": "EXECUTED",
                    "teamId": 1,
                    "scoringPeriodId": 3,
                    "bidAmount": 7,
                    "proposedDate": 1789470515522,
                    "processDate": 1789542000000,
                    "items": [
                        {"type": "ADD", "playerId": 1000, "fromTeamId": 0, "toTeamId": 1},
                        {"type": "DROP", "playerId": 5002, "fromTeamId": 1, "toTeamId": 0},
                    ],
                },
                {
                    "id": "tx-lineup",
                    "type": "ROSTER",
                    "status": "EXECUTED",
                    "teamId": 2,
                    "scoringPeriodId": 3,
                    "items": [{"type": "LINEUP", "playerId": 1013, "fromTeamId": 0, "toTeamId": 0}],
                },
                {
                    "id": "tx-failed-claim",
                    "type": "WAIVER",
                    "status": "FAILED_INVALIDPLAYERSOURCE",  # a real ESPN value, 26 chars
                    "teamId": 3,
                    "scoringPeriodId": 3,
                    "items": [{"type": "ADD", "playerId": 1000, "fromTeamId": 0, "toTeamId": 3}],
                },
            ],
            4: [
                {
                    "id": "tx-trade",
                    "type": "TRADE_ACCEPT",
                    "status": "EXECUTED",
                    "teamId": 2,
                    "scoringPeriodId": 4,
                    "proposedDate": 1789600000000,
                    "items": [
                        {"type": "TRADE", "playerId": 1013, "fromTeamId": 2, "toTeamId": 3},
                        {"type": "TRADE", "playerId": 1025, "fromTeamId": 3, "toTeamId": 2},
                    ],
                },
            ],
        },
    }


def build_scoreboard() -> dict[str, Any]:
    """Week 4's NFL games in the site API's shape: one final, one live, one upcoming.

    Every other pro team is on bye. Uses the scoreboard's own abbreviation for Washington.
    """

    def event(eid: str, home: str, away: str, state: str, detail: str, date: str, hs, as_):
        return {
            "id": eid,
            "date": date,
            "competitions": [
                {
                    "status": {"type": {"state": state, "shortDetail": detail}},
                    "competitors": [
                        {"homeAway": "home", "team": {"abbreviation": home}, "score": hs},
                        {"homeAway": "away", "team": {"abbreviation": away}, "score": as_},
                    ],
                }
            ],
        }

    return {
        "week": {"number": CURRENT_WEEK},
        "events": [
            event("401", "BUF", "DAL", "post", "Final", "2026-10-04T17:00Z", "27", "20"),
            event("402", "DEN", "DET", "in", "Q3 4:12", "2026-10-04T20:05Z", "14", "10"),
            event("403", "GB", "WAS", "pre", "10/5 - 8:15 PM EDT", "2099-10-05T00:15Z", "0", "0"),
        ],
    }


class FakeEspn:
    """Routes requests by `view` params. Records calls; can be told to fail."""

    def __init__(self, league: dict[str, Any] | None = None) -> None:
        self.league = league or build_league()
        self.scoreboard = build_scoreboard()
        self.calls: list[httpx.Request] = []
        self.fail_with: list[int] = []  # status codes to return, popped per request
        # When set, the league is private: only these espn_s2 cookie values may read it.
        self.allowed_s2: set[str] | None = None

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.fail_with:
            return httpx.Response(self.fail_with.pop(0), text="nope")
        if request.url.host == "site.api.espn.com":
            return httpx.Response(200, json=self.scoreboard)
        if not request.url.path.endswith(f"/seasons/{SEASON}/segments/0/leagues/{LEAGUE_ID}"):
            return httpx.Response(404, text="not found")
        if self.allowed_s2 is not None:
            cookies = dict(
                c.strip().split("=", 1)
                for c in request.headers.get("cookie", "").split(";")
                if "=" in c
            )
            if cookies.get("espn_s2") not in self.allowed_s2:
                return httpx.Response(401, json={"messages": ["not authorized"]})
        views = request.url.params.get_list("view")
        period = int(request.url.params.get("scoringPeriodId") or CURRENT_WEEK)
        lg = self.league
        body: dict[str, Any] = {
            "id": int(LEAGUE_ID),
            "seasonId": SEASON,
            "scoringPeriodId": CURRENT_WEEK,
            "status": {"currentMatchupPeriod": CURRENT_WEEK, "latestScoringPeriod": CURRENT_WEEK},
        }
        if "mSettings" in views:
            body["settings"] = lg["settings"]
        if "mTeam" in views or "mRoster" in views:
            body["members"] = lg["members"]
            body["teams"] = [
                t if "mRoster" in views else {k: v for k, v in t.items() if k != "roster"}
                for t in lg["teams"]
            ]
        if "mMatchupScore" in views:
            body["schedule"] = lg["schedule"]
        if "mTransactions2" in views:
            body["transactions"] = lg["transactions"].get(period, [])
        if "kona_player_info" in views:
            body["players"] = lg["free_agents"]
        if "kona_playercard" in views:
            flt = json.loads(request.headers.get("X-Fantasy-Filter", "{}"))
            ids = set(flt.get("players", {}).get("filterIds", {}).get("value", []))
            body["players"] = [
                {"id": e["playerId"], "player": e["playerPoolEntry"]["player"]}
                for t in lg["teams"]
                for e in t["roster"]["entries"]
                if e["playerId"] in ids
            ]
        return httpx.Response(200, json=body)
