from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from fantasy_gm.api.app import create_app
from fantasy_gm.db import League, ProGame, init_db, session_scope
from fantasy_gm.espn.parse import parse_pro_games
from fantasy_gm.sync import games_active, needs_live_refresh, refresh_live
from tests.fake_espn import CURRENT_WEEK, LEAGUE_ID, SEASON, build_scoreboard


@pytest.fixture
def api(db):
    with TestClient(create_app(db, start_scheduler=False)) as c:
        r = c.post("/api/leagues", json={"league_id": LEAGUE_ID, "season": SEASON})
        assert r.status_code == 201, r.text
        c.league_id = r.json()["id"]
        c.settings = db
        yield c


def test_parse_pro_games():
    games = {g.external_id: g for g in parse_pro_games(build_scoreboard(), SEASON, 4)}
    final, live, upcoming = games["401"], games["402"], games["403"]
    assert (final.home_team, final.away_team, final.home_score, final.state) == (
        "BUF",
        "DAL",
        27,
        "post",
    )
    assert live.state == "in" and live.detail == "Q3 4:12"
    assert upcoming.away_team == "WSH"  # scoreboard's "WAS" mapped to fantasy's abbreviation
    assert upcoming.home_score is None  # no score before kickoff
    assert upcoming.kickoff == datetime(2099, 10, 5, 0, 15, tzinfo=UTC)


def _game(state: str, kickoff: datetime | None) -> ProGame:
    return ProGame(state=state, kickoff=kickoff)


def test_games_active_windows():
    now = datetime(2026, 10, 4, 12, tzinfo=UTC)
    assert games_active([_game("in", now - timedelta(hours=1))], now)
    assert games_active([_game("pre", now + timedelta(minutes=30))], now)  # pregame window
    assert not games_active([_game("pre", now + timedelta(hours=5))], now)
    assert not games_active([_game("post", now - timedelta(hours=4))], now)
    # Stored as upcoming but kickoff has passed: our copy is stale, so refresh.
    assert games_active([_game("pre", now - timedelta(minutes=5))], now)


def test_game_status_on_roster(api):
    team = api.get(f"/api/leagues/{api.league_id}/teams/1").json()
    games = {p["name"]: p["game"] for p in team["roster"]}
    assert games["QB"]["state"] == "post"
    assert (games["QB"]["team_score"], games["QB"]["opponent_score"]) == (27, 20)
    assert games["QB"]["opponent"] == "DAL" and games["QB"]["is_home"] is True
    assert games["RB2"]["state"] == "in"  # DEN
    assert games["WR2"]["state"] == "pre"  # GB
    assert games["TE"]["state"] == "bye"  # TEN not playing


def test_overview_live_block(api):
    ov = api.get(f"/api/leagues/{api.league_id}").json()
    assert ov["live"]["active"] is True  # DEN-DET is in progress
    assert len(ov["live"]["games"]) == 3
    assert ov["live_updated_at"] is not None
    mine = next(m for m in ov["current_matchups"] if m["home_team_id"] == 1)
    # Starters: QB+RB1 final, RB2+WR1 live, WR2 upcoming, the rest on bye.
    assert mine["home_lineup"] == {"played": 2, "playing": 2, "yet_to_play": 1}


def test_refresh_live_updates_points_scores_and_lineups(api, fake):
    team = fake.league["teams"][0]
    qb = team["roster"]["entries"][0]
    qb["playerPoolEntry"]["player"]["stats"].append(
        {
            "seasonId": SEASON,
            "scoringPeriodId": CURRENT_WEEK,
            "statSourceId": 0,
            "statSplitTypeId": 1,
            "appliedTotal": 18.4,
        }
    )
    team["roster"]["entries"][9]["lineupSlotId"] = 23  # bench WR -> FLEX
    team["roster"]["entries"][6]["lineupSlotId"] = 20  # FLEX WR -> bench
    week4 = next(m for m in fake.league["schedule"] if m["matchupPeriodId"] == CURRENT_WEEK)
    week4["home"].update(totalPointsLive=77.7, winProbability=0.81)
    week4["away"]["winProbability"] = 0.19
    fake.scoreboard["events"][1]["competitions"][0]["status"]["type"] = {
        "state": "post",
        "shortDetail": "Final",
    }

    calls_before = len(fake.calls)
    assert refresh_live(api.league_id, api.settings, force=True) is True
    views = [v for c in fake.calls[calls_before:] for v in c.url.params.get_list("view")]
    assert sorted(views) == ["mMatchupScore", "mRoster"]  # cheap: no free agents etc.

    roster = api.get(f"/api/leagues/{api.league_id}/teams/1").json()["roster"]
    by_name = {p["name"]: p for p in roster}
    assert by_name["QB"]["value"]["this_week_actual"] == 18.4
    assert by_name["Bench WR"]["slot"] == "FLEX"
    assert by_name["RB2"]["game"]["state"] == "post"

    ov = api.get(f"/api/leagues/{api.league_id}").json()
    mine = next(m for m in ov["current_matchups"] if m["home_team_id"] == 1)
    assert mine["home_points"] == 77.7
    assert (mine["home_win_prob"], mine["away_win_prob"]) == (0.81, 0.19)


def test_refresh_live_skips_when_no_games_on(api, fake):
    with session_scope() as s:
        for g in s.query(ProGame):
            g.state = "post"
    calls_before = len(fake.calls)
    assert refresh_live(api.league_id, api.settings) is False
    assert len(fake.calls) == calls_before


def test_needs_refresh_when_week_games_unknown(api):
    with session_scope() as s:
        s.query(ProGame).delete()
        league = s.get(League, api.league_id)
        assert needs_live_refresh(s, league)


def test_new_columns_added_to_existing_database(tmp_path):
    url = f"sqlite:///{tmp_path / 'old.db'}"
    engine = create_engine(url)
    with engine.begin() as conn:  # a leagues table from before live_updated_at existed
        conn.execute(
            text(
                "CREATE TABLE leagues (id INTEGER PRIMARY KEY, platform VARCHAR(16), "
                "external_id VARCHAR(64), season INTEGER, name VARCHAR(200), "
                "current_week INTEGER, final_regular_week INTEGER, my_team_id INTEGER, "
                "settings JSON, last_synced_at DATETIME)"
            )
        )
    engine.dispose()
    init_db(url)
    cols = {c["name"] for c in inspect(create_engine(url)).get_columns("leagues")}
    assert "live_updated_at" in cols


def test_players_locked_once_their_game_starts(api):
    roster = {
        p["name"]: p for p in api.get(f"/api/leagues/{api.league_id}/teams/1").json()["roster"]
    }
    assert roster["QB"]["locked"] is True  # BUF: final
    assert roster["RB2"]["locked"] is True  # DEN: in progress
    assert roster["WR2"]["locked"] is False  # GB: not started
    assert roster["TE"]["locked"] is False  # bye


def test_trade_search_can_skip_locked_players(api):
    url = f"/api/leagues/{api.league_id}/trades"
    everything = api.get(url).json()["trades"]
    assert any(not t["tradeable_now"] for t in everything)  # some involve players who've played

    now = api.get(url, params={"tradeable_now": "true"}).json()["trades"]
    assert now, "expected some trades among unlocked players"
    for t in now:
        assert t["tradeable_now"]
        assert not any(p["locked"] for p in [*t["give"], *t["get"]])


def test_assistant_trade_tool_respects_tradeable_now(api):
    from fantasy_gm.analytics.league import load_league
    from fantasy_gm.chat import LeagueContext, TradeSearchArgs, t_find_trades

    with session_scope() as s:
        ctx = LeagueContext(load_league(s, api.league_id))
        trades = t_find_trades(ctx, TradeSearchArgs(tradeable_now=True, limit=20))
    assert trades
    for t in trades:
        assert t["tradeable_now"]
        assert not any(p["locked"] for p in [*t["give"], *t["get"]])
