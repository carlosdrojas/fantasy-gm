"""Pure functions: raw ESPN JSON -> platform-agnostic domain objects.

ESPN's payloads are undocumented and fields come and go, so every accessor here
tolerates missing keys rather than raising.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fantasy_gm.domain import (
    MatchupData,
    PlayerData,
    ProGameData,
    RosterSlotData,
    TeamData,
    TransactionData,
    TransactionItemData,
)
from fantasy_gm.espn.constants import (
    LINEUP_SLOTS,
    POSITIONS,
    PRO_TEAMS,
    SPLIT_SEASON,
    SPLIT_WEEK,
    STAT_SOURCE_ACTUAL,
    STAT_SOURCE_PROJECTED,
    lookup,
)

RECEPTION_STAT_ID = 53


def _d(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _l(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ms_to_dt(value: Any) -> datetime | None:
    ms = _int(value)
    return datetime.fromtimestamp(ms / 1000, tz=UTC) if ms else None


def _team_ext(team_id: Any) -> str | None:
    tid = _int(team_id)
    return str(tid) if tid else None  # ESPN uses 0 / -1 for "no team"


# --- league-level -------------------------------------------------------------


def current_scoring_period(raw: dict[str, Any]) -> int | None:
    status = _d(raw.get("status"))
    return _int(raw.get("scoringPeriodId")) or _int(status.get("latestScoringPeriod"))


def parse_settings(raw: dict[str, Any]) -> dict[str, Any]:
    settings = _d(raw.get("settings"))
    roster = _d(settings.get("rosterSettings"))
    schedule = _d(settings.get("scheduleSettings"))
    scoring = _d(settings.get("scoringSettings"))
    acquisition = _d(settings.get("acquisitionSettings"))

    slot_counts: dict[str, int] = {}
    for slot_id, count in _d(roster.get("lineupSlotCounts")).items():
        n = _int(count)
        if n:
            slot_counts[lookup(LINEUP_SLOTS, slot_id)] = n

    reception_points = 0.0
    for item in _l(scoring.get("scoringItems")):
        if _int(_d(item).get("statId")) == RECEPTION_STAT_ID:
            reception_points = _float(item.get("points")) or 0.0

    return {
        "lineup_slot_counts": slot_counts,
        "scoring_type": scoring.get("scoringType"),
        "reception_points": reception_points,
        "regular_season_weeks": _int(schedule.get("matchupPeriodCount")),
        "playoff_team_count": _int(schedule.get("playoffTeamCount")),
        "uses_faab": bool(acquisition.get("isUsingAcquisitionBudget")),
        "faab_budget": _int(acquisition.get("acquisitionBudget")),
        "team_count": _int(settings.get("size")) or len(_l(raw.get("teams"))),
    }


def find_my_team(raw: dict[str, Any], swid: str | None) -> str | None:
    if not swid:
        return None
    swid = swid.lower()
    for team in _l(raw.get("teams")):
        if swid in [str(o).lower() for o in _l(_d(team).get("owners"))]:
            return str(team.get("id"))
    return None


# --- teams & rosters ----------------------------------------------------------


def _member_names(raw: dict[str, Any]) -> dict[str, str]:
    names: dict[str, str] = {}
    for m in _l(raw.get("members")):
        m = _d(m)
        full = f"{m.get('firstName') or ''} {m.get('lastName') or ''}".strip()
        names[str(m.get("id", "")).lower()] = full or m.get("displayName") or "Unknown"
    return names


def parse_teams(raw: dict[str, Any]) -> list[TeamData]:
    members = _member_names(raw)
    teams: list[TeamData] = []
    for t in _l(raw.get("teams")):
        t = _d(t)
        if t.get("id") is None:
            continue
        overall = _d(_d(t.get("record")).get("overall"))
        owners = [str(o) for o in _l(t.get("owners"))]
        name = t.get("name") or f"{t.get('location') or ''} {t.get('nickname') or ''}".strip()
        teams.append(
            TeamData(
                external_id=str(t["id"]),
                name=name or f"Team {t['id']}",
                abbrev=t.get("abbrev"),
                owner_name=members.get(owners[0].lower()) if owners else None,
                owner_ids=owners,
                wins=_int(overall.get("wins")) or 0,
                losses=_int(overall.get("losses")) or 0,
                ties=_int(overall.get("ties")) or 0,
                points_for=_float(overall.get("pointsFor")) or 0.0,
                points_against=_float(overall.get("pointsAgainst")) or 0.0,
                playoff_seed=_int(t.get("playoffSeed")),
                waiver_rank=_int(t.get("waiverRank")),
                faab_spent=_int(_d(t.get("transactionCounter")).get("acquisitionBudgetSpent")),
                logo_url=t.get("logo"),
                roster=[
                    RosterSlotData(
                        player_external_id=str(e["playerId"]),
                        slot=lookup(LINEUP_SLOTS, e.get("lineupSlotId")),
                        acquisition_type=e.get("acquisitionType"),
                    )
                    for e in map(_d, _l(_d(t.get("roster")).get("entries")))
                    if e.get("playerId") is not None
                ],
            )
        )
    return teams


def parse_player(entry: dict[str, Any], season: int) -> PlayerData | None:
    """Parse a player from a roster entry or a kona_player_info/kona_playercard item."""
    entry = _d(entry)
    pool = _d(entry.get("playerPoolEntry"))
    player = _d(pool.get("player")) or _d(entry.get("player"))
    pid = player.get("id", entry.get("playerId", entry.get("id")))
    if pid is None or not player:
        return None

    ownership = _d(player.get("ownership"))
    points: dict[tuple[int, str], float] = {}
    for s in map(_d, _l(player.get("stats"))):
        if _int(s.get("seasonId")) != season:
            continue
        total = _float(s.get("appliedTotal"))
        source, split = _int(s.get("statSourceId")), _int(s.get("statSplitTypeId"))
        if total is None or source not in (STAT_SOURCE_ACTUAL, STAT_SOURCE_PROJECTED):
            continue
        kind = "actual" if source == STAT_SOURCE_ACTUAL else "projected"
        if split == SPLIT_SEASON:
            week = 0
        elif split == SPLIT_WEEK:
            week = _int(s.get("scoringPeriodId")) or 0
            if week == 0:
                continue
        else:
            continue
        points[(week, kind)] = round(total, 2)

    injury = player.get("injuryStatus") or pool.get("injuryStatus")
    if injury is None and player.get("injured") is False:
        injury = "ACTIVE"

    return PlayerData(
        external_id=str(pid),
        full_name=player.get("fullName") or f"Player {pid}",
        position=lookup(POSITIONS, player.get("defaultPositionId")),
        pro_team=lookup(PRO_TEAMS, player.get("proTeamId")),
        injury_status=injury,
        eligible_slots=[lookup(LINEUP_SLOTS, s) for s in _l(player.get("eligibleSlots"))],
        percent_owned=_float(ownership.get("percentOwned")),
        percent_owned_change=_float(ownership.get("percentChange")),
        points=points,
    )


def rostered_players(raw: dict[str, Any], season: int) -> list[PlayerData]:
    players = []
    for team in _l(raw.get("teams")):
        for e in _l(_d(_d(team).get("roster")).get("entries")):
            p = parse_player(e, season)
            if p:
                players.append(p)
    return players


def merge_players(*groups: list[PlayerData]) -> list[PlayerData]:
    """Combine player lists; later groups fill gaps and add points, never erase."""
    merged: dict[str, PlayerData] = {}
    for group in groups:
        for p in group:
            cur = merged.get(p.external_id)
            if cur is None:
                merged[p.external_id] = p
                continue
            cur.points.update(p.points)
            for attr in ("pro_team", "injury_status", "percent_owned", "percent_owned_change"):
                if getattr(p, attr) is not None:
                    setattr(cur, attr, getattr(p, attr))
            if p.eligible_slots:
                cur.eligible_slots = p.eligible_slots
    return list(merged.values())


# --- schedule & transactions --------------------------------------------------


def parse_matchups(raw: dict[str, Any]) -> list[MatchupData]:
    matchups: list[MatchupData] = []
    for m in map(_d, _l(raw.get("schedule"))):
        home, away = _d(m.get("home")), _d(m.get("away"))
        home_id = _team_ext(home.get("teamId"))
        week = _int(m.get("matchupPeriodId"))
        if m.get("id") is None or home_id is None or week is None:
            continue
        winner = str(m.get("winner") or "UNDECIDED")
        live = winner == "UNDECIDED"

        def pts(side: dict[str, Any], live: bool = live) -> float | None:
            if not side:
                return None
            if live and side.get("totalPointsLive") is not None:
                return _float(side.get("totalPointsLive"))
            return _float(side.get("totalPoints"))

        def proj(side: dict[str, Any]) -> float | None:
            if not side:
                return None
            return _float(side.get("totalProjectedPointsLive", side.get("totalProjectedPoints")))

        matchups.append(
            MatchupData(
                external_id=str(m["id"]),
                week=week,
                home_team_external_id=home_id,
                away_team_external_id=_team_ext(away.get("teamId")),
                home_points=pts(home),
                away_points=pts(away),
                home_projected=proj(home),
                away_projected=proj(away),
                winner=winner,
                is_playoff=(m.get("playoffTierType") or "NONE") != "NONE",
                home_win_prob=_float(home.get("winProbability")) if live else None,
                away_win_prob=_float(away.get("winProbability")) if live else None,
            )
        )
    return matchups


# The NFL scoreboard's abbreviations, where they differ from fantasy's PRO_TEAMS.
SCOREBOARD_TEAM_ALIASES = {"WAS": "WSH", "LA": "LAR", "JAC": "JAX"}


def parse_pro_games(raw: dict[str, Any], season: int, week: int) -> list[ProGameData]:
    games: list[ProGameData] = []
    for event in map(_d, _l(raw.get("events"))):
        comp = _d(_l(event.get("competitions"))[0]) if _l(event.get("competitions")) else {}
        sides: dict[str, dict[str, Any]] = {}
        for c in map(_d, _l(comp.get("competitors"))):
            sides[str(c.get("homeAway"))] = c
        home, away = sides.get("home"), sides.get("away")
        if event.get("id") is None or not home or not away:
            continue
        status = _d(comp.get("status")) or _d(event.get("status"))
        kind = _d(status.get("type"))

        def abbrev(c: dict[str, Any]) -> str:
            a = str(_d(c.get("team")).get("abbreviation") or "")
            return SCOREBOARD_TEAM_ALIASES.get(a, a)

        state = str(kind.get("state") or "pre")
        games.append(
            ProGameData(
                external_id=str(event["id"]),
                season=season,
                week=week,
                home_team=abbrev(home),
                away_team=abbrev(away),
                home_score=_int(home.get("score")) if state != "pre" else None,
                away_score=_int(away.get("score")) if state != "pre" else None,
                state=state,
                detail=str(kind.get("shortDetail") or kind.get("detail") or ""),
                kickoff=_iso_to_dt(event.get("date")),
            )
        )
    return games


def _iso_to_dt(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


ROSTER_ITEM_TYPES = {"ADD", "DROP", "TRADE"}


def parse_transactions(raw: dict[str, Any]) -> list[TransactionData]:
    """Adds, drops, waivers and trades. Pure lineup moves are skipped as noise."""
    out: list[TransactionData] = []
    for t in map(_d, _l(raw.get("transactions"))):
        items = [
            TransactionItemData(
                type=str(i.get("type")),
                player_external_id=str(i["playerId"]) if i.get("playerId") is not None else None,
                from_team_external_id=_team_ext(i.get("fromTeamId")),
                to_team_external_id=_team_ext(i.get("toTeamId")),
            )
            for i in map(_d, _l(t.get("items")))
            if i.get("type") in ROSTER_ITEM_TYPES
        ]
        if t.get("id") is None or not items:
            continue
        out.append(
            TransactionData(
                external_id=str(t["id"]),
                type=str(t.get("type") or "UNKNOWN"),
                status=str(t.get("status") or "UNKNOWN"),
                team_external_id=_team_ext(t.get("teamId")),
                week=_int(t.get("scoringPeriodId")),
                bid_amount=_int(t.get("bidAmount")),
                proposed_at=_ms_to_dt(t.get("proposedDate")),
                processed_at=_ms_to_dt(t.get("processDate")),
                items=items,
            )
        )
    return out
