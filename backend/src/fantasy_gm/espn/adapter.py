"""ESPN implementation of LeagueSource: orchestrates requests into one snapshot."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from fantasy_gm.domain import LeagueSnapshot, LiveSnapshot, ProGameData, TransactionData
from fantasy_gm.espn import parse
from fantasy_gm.espn.client import EspnClient, EspnError

log = logging.getLogger(__name__)

FREE_AGENT_LIMIT = 250


def _history_filter(player_ids: list[int], season: int, through_week: int) -> dict:
    """Ask ESPN for season totals plus weekly actual/projected points per player."""
    stat_ids = [f"00{season}", f"10{season}"]
    for week in range(1, through_week + 1):
        stat_ids += [f"01{season}{week}", f"11{season}{week}"]
    return {
        "players": {
            "filterIds": {"value": player_ids},
            # "value" is how many of the player's most recent games to include. ESPN
            # doesn't reliably honor the per-week ids above, so ask for every week so far
            # (plus slack; earlier seasons' games are dropped when parsing).
            "filterStatsForTopScoringPeriodIds": {
                "value": through_week + 2,
                "additionalValue": stat_ids,
            },
        }
    }


class EspnSource:
    platform = "espn"

    def __init__(self, client: EspnClient) -> None:
        self.client = client

    def pro_games(self, season: int, week: int) -> list[ProGameData]:
        """NFL game states for the week. Best effort: an empty list if unavailable."""
        try:
            return parse.parse_pro_games(self.client.nfl_scoreboard(season, week), season, week)
        except EspnError as e:
            log.warning("NFL scoreboard fetch failed: %s", e)
            return []

    def fetch_live(self, external_id: str, season: int, week: int) -> LiveSnapshot:
        """The fast-changing slice of a league: lineups, this week's points, scores, games.

        Two league requests plus the public scoreboard, so it is cheap enough to run every
        minute while games are on.
        """
        c = self.client
        rosters = c.league(external_id, season, ["mRoster"], scoring_period=week)
        schedule = c.league(external_id, season, ["mMatchupScore"])
        return LiveSnapshot(
            platform=self.platform,
            external_id=str(external_id),
            season=season,
            week=week,
            rosters={t.external_id: t.roster for t in parse.parse_teams(rosters)},
            players=parse.rostered_players(rosters, season),
            matchups=parse.parse_matchups(schedule),
            pro_games=self.pro_games(season, week),
        )

    def fetch_snapshot(
        self,
        external_id: str,
        season: int,
        *,
        transaction_weeks: Iterable[int] | None = None,
    ) -> LeagueSnapshot:
        """Fetch everything we store for a league.

        ``transaction_weeks`` limits which scoring periods' transactions are
        fetched (incremental syncs); ``None`` fetches the whole season so far.
        """
        c = self.client
        status = c.league(external_id, season, ["mSettings", "mStatus"])
        week = parse.current_scoring_period(status) or 1

        core = c.league(
            external_id,
            season,
            ["mTeam", "mRoster", "mSettings", "mStandings"],
            scoring_period=week,
        )
        schedule = c.league(external_id, season, ["mMatchupScore"])

        rostered = parse.rostered_players(core, season)
        history = []
        if rostered:
            ids = [int(p.external_id) for p in rostered if p.external_id.lstrip("-").isdigit()]
            try:
                data = c.league(
                    external_id,
                    season,
                    ["kona_playercard"],
                    scoring_period=week,
                    fantasy_filter=_history_filter(ids, season, week),
                )
                history = [
                    p for e in data.get("players") or [] if (p := parse.parse_player(e, season))
                ]
            except EspnError as e:  # history is a nice-to-have; don't fail the sync
                log.warning("Player history fetch failed: %s", e)

        try:
            free_agents = [
                p
                for e in c.free_agents(
                    external_id, season, scoring_period=week, limit=FREE_AGENT_LIMIT
                )
                if (p := parse.parse_player(e, season))
            ]
        except EspnError as e:
            log.warning("Free agent fetch failed: %s", e)
            free_agents = []

        weeks = list(transaction_weeks) if transaction_weeks is not None else range(1, week + 1)
        transactions: dict[str, TransactionData] = {}
        for w in weeks:
            if w < 1:
                continue
            raw = c.league(external_id, season, ["mTransactions2"], scoring_period=w)
            for t in parse.parse_transactions(raw):
                transactions[t.external_id] = t

        settings = parse.parse_settings(status) | {
            k: v for k, v in parse.parse_settings(core).items() if v not in (None, {}, 0)
        }
        return LeagueSnapshot(
            platform=self.platform,
            external_id=str(external_id),
            season=season,
            name=(core.get("settings") or {}).get("name")
            or (status.get("settings") or {}).get("name"),
            current_week=week,
            final_regular_week=settings.get("regular_season_weeks"),
            settings=settings,
            my_team_external_id=parse.find_my_team(core, c.swid),
            teams=parse.parse_teams(core),
            players=parse.merge_players(rostered, history, free_agents),
            matchups=parse.parse_matchups(schedule),
            transactions=list(transactions.values()),
            pro_games=self.pro_games(season, week),
        )
