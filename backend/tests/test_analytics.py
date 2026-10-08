import pytest

from fantasy_gm.analytics.lineup import LineupPlayer, lineup_total, optimal_lineup
from fantasy_gm.analytics.power import GameResult, all_play, power_scores
from fantasy_gm.analytics.values import player_value

SLOTS = {"QB": 1, "RB": 2, "WR": 2, "FLEX": 1, "BE": 5}


def lp(pid, slots, value, **kw):
    return LineupPlayer(pid, tuple(slots), value, **kw)


def test_optimal_lineup_uses_flex_for_best_leftover():
    players = [
        lp(1, ["QB"], 20),
        lp(2, ["RB", "FLEX"], 15),
        lp(3, ["RB", "FLEX"], 12),
        lp(4, ["RB", "FLEX"], 11),
        lp(5, ["WR", "FLEX"], 14),
        lp(6, ["WR", "FLEX"], 10),
        lp(7, ["WR", "FLEX"], 9),
    ]
    lineup = optimal_lineup(players, SLOTS)
    assert [p.player_id for p in lineup["FLEX"]] == [4]
    assert lineup_total(lineup) == 20 + 15 + 12 + 14 + 10 + 11


def test_optimal_lineup_skips_ir_and_injured():
    players = [
        lp(1, ["QB"], 30, injury_status="OUT"),
        lp(2, ["QB"], 10),
        lp(3, ["QB"], 40, on_ir=True),
    ]
    assert optimal_lineup(players, {"QB": 1})["QB"][0].player_id == 2
    # Season-long strength still counts the injured (but not IR) player.
    assert optimal_lineup(players, {"QB": 1}, respect_injuries=False)["QB"][0].player_id == 1


def test_optimal_lineup_leaves_slot_empty_when_nobody_eligible():
    assert optimal_lineup([lp(1, ["QB"], 10)], {"QB": 1, "TE": 1})["TE"] == []


def test_all_play_and_luck():
    scores = {
        1: {1: 110, 2: 140, 3: 100, 4: 90},
        2: {1: 95, 2: 150, 3: 120, 4: 80},
        3: {1: 130, 2: 125, 3: 105, 4: 70},
    }
    wins = {(1, 1): False, (2, 1): False, (3, 1): True}
    results = [
        GameResult(w, t, p, wins.get((w, t), True)) for w, s in scores.items() for t, p in s.items()
    ]
    power = all_play(results)
    me = power[1]
    assert (me.all_play_wins, me.all_play_losses) == (6, 3)
    assert me.expected_wins == pytest.approx(2.0)
    assert me.actual_wins == 1 and me.luck == -1.0
    assert power[2].all_play_wins == 8


def test_power_scores_preseason_uses_roster_strength_only():
    out = power_scores({}, {1: 100.0, 2: 80.0})
    assert out[1]["score"] == 100.0 and out[2]["score"] == 0.0


def test_player_value_blends_and_trends():
    pts = {
        (0, "projected"): 170.0,
        (1, "actual"): 4.0,
        (2, "actual"): 0.0,
        (3, "actual"): 12.0,
        (4, "actual"): 16.0,
        (5, "actual"): 20.0,
        (6, "projected"): 11.0,
    }
    v = player_value(pts, current_week=6)
    assert v.projected_per_game == 10.0
    assert v.recent_avg == 13.0  # zero (bye) excluded
    assert v.per_game == pytest.approx(0.6 * 10 + 0.4 * 13)
    assert v.trend > 0 and v.this_week_projection == 11.0


def test_player_value_without_projection():
    assert player_value({(1, "actual"): 8.0}, current_week=2).per_game == 8.0
    assert player_value({}, current_week=2).per_game == 0.0
