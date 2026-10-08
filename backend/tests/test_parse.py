from fantasy_gm.espn import parse
from tests.fake_espn import CURRENT_WEEK, MY_SWID, SEASON, build_league


def raw_league():
    lg = build_league()
    return {
        "settings": lg["settings"],
        "teams": lg["teams"],
        "members": lg["members"],
        "schedule": lg["schedule"],
        "scoringPeriodId": CURRENT_WEEK,
    }


def test_settings():
    s = parse.parse_settings(raw_league())
    assert s["lineup_slot_counts"] == {
        "QB": 1,
        "RB": 2,
        "WR": 2,
        "TE": 1,
        "FLEX": 1,
        "D/ST": 1,
        "K": 1,
        "BE": 7,
        "IR": 1,
    }
    assert s["reception_points"] == 1.0
    assert s["uses_faab"] and s["faab_budget"] == 100
    assert s["regular_season_weeks"] == 14


def test_teams_and_my_team():
    raw = raw_league()
    teams = parse.parse_teams(raw)
    assert [t.name for t in teams] == ["Mine", "Juggernaut", "Middling", "Tankers"]
    assert teams[0].owner_name == "Carlos R"
    assert teams[1].owner_name == "bee"
    assert teams[0].roster[0].slot == "QB"
    assert {r.slot for r in teams[0].roster} >= {"FLEX", "BE", "IR", "D/ST"}
    assert parse.find_my_team(raw, MY_SWID.lower()) == "1"
    assert parse.find_my_team(raw, None) is None


def test_player_points_filters_other_seasons():
    entry = raw_league()["teams"][0]["roster"]["entries"][0]
    p = parse.parse_player(entry, SEASON)
    assert p.position == "QB" and p.pro_team == "BUF"
    assert p.points[(0, "projected")] == 340.0
    assert p.points[(1, "actual")] == 20.0
    assert p.points[(CURRENT_WEEK, "projected")] == 20.0
    assert 999 not in p.points.values()  # last season's total ignored
    assert "FLEX" not in p.eligible_slots and "QB" in p.eligible_slots


def test_player_tolerates_garbage():
    assert parse.parse_player({}, SEASON) is None
    p = parse.parse_player({"id": 7, "player": {"stats": "nope", "defaultPositionId": 99}}, SEASON)
    assert p.full_name == "Player 7" and p.position.startswith("UNK")


def test_matchups_live_and_final():
    ms = parse.parse_matchups(raw_league())
    final = next(m for m in ms if m.week == 1)
    live = next(m for m in ms if m.week == CURRENT_WEEK)
    assert final.winner == "AWAY" and final.home_points == 110
    assert live.home_points == 42.5 and live.home_projected == 120.1


def test_matchup_bye_has_no_away():
    ms = parse.parse_matchups(
        {"schedule": [{"id": 1, "matchupPeriodId": 1, "home": {"teamId": 3, "totalPoints": 80}}]}
    )
    assert ms[0].away_team_external_id is None and ms[0].away_points is None


def test_transactions_skip_lineup_moves():
    txns = build_league()["transactions"][3]
    out = parse.parse_transactions({"transactions": txns})
    assert [t.external_id for t in out] == ["tx-waiver", "tx-failed-claim"]
    t = out[0]
    assert t.bid_amount == 7 and t.proposed_at.year == 2026
    assert t.items[0].from_team_external_id is None and t.items[0].to_team_external_id == "1"


def test_merge_players_keeps_points_from_all_sources():
    a = parse.PlayerData("1", "A", "RB", points={(1, "actual"): 5})
    b = parse.PlayerData("1", "A", "RB", percent_owned=40, points={(2, "actual"): 7})
    [m] = parse.merge_players([a], [b])
    assert m.points == {(1, "actual"): 5, (2, "actual"): 7} and m.percent_owned == 40
