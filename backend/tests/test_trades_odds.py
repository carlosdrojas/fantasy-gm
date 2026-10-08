import numpy as np
import pytest

from fantasy_gm.analytics.league import load_league
from fantasy_gm.analytics.simulate import _bracket_champions, simulate
from fantasy_gm.analytics.trades import MIN_MY_GAIN, acceptance, evaluate_trade, find_trades
from fantasy_gm.db import session_scope
from fantasy_gm.sync import add_espn_league
from tests.fake_espn import LEAGUE_ID, SEASON


@pytest.fixture
def data(db):
    lid = add_espn_league(LEAGUE_ID, SEASON, db)
    with session_scope() as s:
        d = load_league(s, lid)
        names = {t.name: t.id for t in d.teams.values()}
        yield d, names


def test_find_trades_targets_my_rb_need(data):
    d, names = data
    trades = find_trades(d, names["Mine"], limit=50)
    assert trades
    assert all(t["my_gain"] >= MIN_MY_GAIN for t in trades)
    # My weak spot is RB, so some ideas bring RBs back...
    assert any(p["position"] == "RB" for t in trades for p in t["get"])
    # ...but never asks so lopsided nobody would accept (e.g. my WR1 for their elite RB).
    assert all(t["raw_value_edge"] <= 4.0 for t in trades)
    assert all(p["position"] not in ("K", "D/ST") for t in trades for p in t["give"] + t["get"])


def test_sort_modes(data):
    d, names = data
    by_gain = find_trades(d, names["Mine"], sort="gain", limit=50)
    likely = find_trades(d, names["Mine"], sort="likely", limit=50)
    assert [t["my_gain"] for t in by_gain] == sorted((t["my_gain"] for t in by_gain), reverse=True)
    assert [t["acceptance"] for t in likely] == sorted(
        (t["acceptance"] for t in likely), reverse=True
    )


def test_trades_that_hurt_partner_are_kept(data):
    d, names = data
    trades = find_trades(d, names["Mine"], sort="gain", limit=100)
    assert any(t["their_gain"] < 0 for t in trades)


def test_partner_filter(data):
    d, names = data
    trades = find_trades(d, names["Mine"], names["Juggernaut"])
    assert {t["partner_team_id"] for t in trades} <= {names["Juggernaut"]}


def test_evaluate_trade_is_symmetric(data):
    d, names = data
    me, them = names["Mine"], names["Middling"]
    give = [next(r.player.id for r in d.rosters[me] if r.player.full_name == "Bench WR")]
    get = [next(r.player.id for r in d.rosters[them] if r.player.full_name == "RB1")]
    mine = evaluate_trade(d, me, them, give, get)
    theirs = evaluate_trade(d, them, me, get, give)
    assert mine["my_gain"] == theirs["their_gain"]
    assert mine["their_gain"] == theirs["my_gain"]
    assert mine["my_gain"] > 0


def test_evaluate_trade_rejects_wrong_roster(data):
    d, names = data
    wrong = [d.rosters[names["Tankers"]][0].player.id]
    with pytest.raises(ValueError):
        evaluate_trade(d, names["Mine"], names["Middling"], wrong, wrong)


def test_acceptance_monotonic():
    assert acceptance(2, 0) > acceptance(0, 0) > acceptance(-2, 0)
    assert acceptance(0, -2) > acceptance(0, 0) > acceptance(0, 3)


def test_simulation_probabilities(data):
    d, names = data
    odds = simulate(d, n_sims=4000, seed=1)
    assert sum(o["playoff_pct"] for o in odds.values()) == pytest.approx(200, abs=0.5)
    assert sum(o["champion_pct"] for o in odds.values()) == pytest.approx(100, abs=0.5)
    assert sum(o["first_seed_pct"] for o in odds.values()) == pytest.approx(100, abs=0.5)
    best = max(odds, key=lambda t: odds[t]["champion_pct"])
    assert best == names["Juggernaut"]
    assert odds[names["Tankers"]]["playoff_pct"] < odds[names["Juggernaut"]]["playoff_pct"]
    # 11 weeks left (4-14) but the fake schedule only defines week 4.
    assert all(o["avg_wins"] >= d.teams[t].wins for t, o in odds.items())


def test_simulation_is_deterministic(data):
    d, _ = data
    assert simulate(d, n_sims=500) == simulate(d, n_sims=500)


def test_strength_override_moves_odds(data):
    d, names = data
    base = simulate(d, n_sims=3000, seed=2)
    boosted = simulate(d, n_sims=3000, seed=2, strength_override={names["Mine"]: 400.0})
    # This week is live (ESPN projections decide it), so the boost shows up in the playoffs.
    assert boosted[names["Mine"]]["champion_pct"] > base[names["Mine"]]["champion_pct"]


def test_bracket_with_byes():
    rng = np.random.default_rng(0)
    means = np.array([200.0, 190.0, 50.0, 40.0, 30.0, 20.0])
    seeds = np.tile(np.arange(6), (200, 1))
    champs = _bracket_champions(seeds, means, 5.0, rng)
    assert set(champs) <= {0, 1}  # the two bye teams are far stronger
