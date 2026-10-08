import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from fantasy_gm.api.app import create_app
from fantasy_gm.db import PlayerPoints, RosterEntry, SyncRun, Transaction, session_scope
from tests.fake_espn import LEAGUE_ID, SEASON


@pytest.fixture
def api(db):
    with TestClient(create_app(db, start_scheduler=False)) as c:
        r = c.post("/api/leagues", json={"league_id": LEAGUE_ID, "season": SEASON})
        assert r.status_code == 201, r.text
        c.league_id = r.json()["id"]
        yield c


def test_overview(api):
    ov = api.get(f"/api/leagues/{api.league_id}").json()
    assert ov["name"] == "Test League" and ov["current_week"] == 4
    assert len(ov["teams"]) == 4
    me = next(t for t in ov["teams"] if t["id"] == ov["my_team_id"])
    assert me["name"] == "Mine"
    assert len(ov["current_matchups"]) == 2


def test_duplicate_add_conflicts(api):
    r = api.post("/api/leagues", json={"league_id": LEAGUE_ID, "season": SEASON})
    assert r.status_code == 409


def test_unknown_league_is_404(api):
    assert api.post("/api/leagues", json={"league_id": "999", "season": SEASON}).status_code == 404


def test_power_rankings(api):
    rows = api.get(f"/api/leagues/{api.league_id}/power").json()
    by_name = {r["team_id"]: r for r in rows}
    ov = api.get(f"/api/leagues/{api.league_id}").json()
    names = {t["id"]: t["name"] for t in ov["teams"]}
    assert names[rows[0]["team_id"]] == "Juggernaut"
    mine = by_name[ov["my_team_id"]]
    assert mine["all_play"]["wins"] == 6 and mine["luck"] == -1.0
    assert [w["week"] for w in mine["weekly_points"]] == [1, 2, 3]


def test_team_detail_suggests_benched_wr(api):
    ov = api.get(f"/api/leagues/{api.league_id}").json()
    d = api.get(f"/api/leagues/{api.league_id}/teams/{ov['my_team_id']}").json()
    names = {p["id"]: p["name"] for p in d["roster"]}
    assert [names[i] for i in d["lineup_changes"]["start"]] == ["Bench WR"]
    assert [names[i] for i in d["lineup_changes"]["sit"]] == ["FLEX WR"]
    assert d["positions"]["RB"]["label"] == "need"
    assert d["roster"][0]["position"] == "QB" and d["roster"][-1]["slot"] == "IR"


def test_positions_matrix(api):
    teams = api.get(f"/api/leagues/{api.league_id}/positions").json()["teams"]
    assert len(teams) == 4
    assert all(set(v) == {"QB", "RB", "WR", "TE", "K", "D/ST"} for v in teams.values())


def test_waivers_rank_rb_for_rb_needy_team(api):
    w = api.get(f"/api/leagues/{api.league_id}/waivers").json()
    top = w["suggestions"][0]
    assert top["player"]["name"] == "Waiver Stud RB"
    assert top["ros_gain"] > 0 and top["drop"]["slot"] == "BE"
    names = [s["player"]["name"] for s in w["suggestions"]]
    assert "Scrub TE" not in names


def test_free_agents_exclude_rostered(api):
    fas = api.get(f"/api/leagues/{api.league_id}/free-agents").json()
    assert {p["name"] for p in fas} == {"Waiver Stud RB", "Hurt WR", "Scrub TE"}
    assert (
        api.get(f"/api/leagues/{api.league_id}/free-agents?position=TE").json()[0]["name"]
        == "Scrub TE"
    )


def test_transactions(api):
    txns = api.get(f"/api/leagues/{api.league_id}/transactions").json()
    assert [t["type"] for t in txns] == ["TRADE_ACCEPT", "WAIVER"]
    assert txns[1]["items"][0]["player"]["name"] == "QB"


def test_resync_is_idempotent(api, fake):
    def counts():
        with session_scope() as s:
            return tuple(
                s.scalar(select(func.count()).select_from(m))
                for m in (RosterEntry, PlayerPoints, Transaction)
            )

    before = counts()
    calls_before = len(fake.calls)
    assert api.post(f"/api/leagues/{api.league_id}/sync").json()["status"] == "ok"
    assert counts() == before
    # Incremental: only recent weeks' transactions re-fetched (weeks 2-4), not 1-4.
    txn_calls = [
        c for c in fake.calls[calls_before:] if "mTransactions2" in c.url.params.get_list("view")
    ]
    assert len(txn_calls) == 3


def test_sync_failure_is_recorded_and_reported(api, fake):
    fake.fail_with = [401]
    r = api.post(f"/api/leagues/{api.league_id}/sync")
    assert r.status_code == 401
    with session_scope() as s:
        run = s.scalars(select(SyncRun).order_by(SyncRun.id.desc())).first()
        assert run.status == "error" and "cookies" in run.error
    ov = api.get(f"/api/leagues/{api.league_id}").json()
    assert ov["last_sync"]["status"] == "error"
    assert len(ov["teams"]) == 4  # old data still served


def test_delete_league(api):
    assert api.delete(f"/api/leagues/{api.league_id}").status_code == 204
    assert api.get("/api/leagues").json() == []


def test_timestamps_are_utc_aware(api):
    ov = api.get(f"/api/leagues/{api.league_id}").json()
    assert ov["last_synced_at"].endswith(("Z", "+00:00"))


def test_odds_endpoint(api):
    body = api.get(f"/api/leagues/{api.league_id}/odds").json()
    assert len(body["teams"]) == 4 and body["remaining_weeks"] == [4]
    assert api.get(f"/api/leagues/{api.league_id}/odds").json() == body  # memoized/deterministic


def test_trades_endpoints(api):
    body = api.get(f"/api/leagues/{api.league_id}/trades?sort=gain").json()
    assert body["trades"]
    t = body["trades"][0]
    r = api.post(
        f"/api/leagues/{api.league_id}/trades/analyze",
        json={
            "partner_team_id": t["partner_team_id"],
            "give": [p["id"] for p in t["give"]],
            "get": [p["id"] for p in t["get"]],
        },
    )
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["my_gain"] == t["my_gain"]
    assert set(res["odds"]) == {str(body["team_id"]), str(t["partner_team_id"])}
    assert api.get(f"/api/leagues/{api.league_id}/trades?sort=nope").status_code == 422


def test_analyze_rejects_players_on_wrong_team(api):
    body = api.get(f"/api/leagues/{api.league_id}/trades").json()
    t = body["trades"][0]
    r = api.post(
        f"/api/leagues/{api.league_id}/trades/analyze",
        json={
            "partner_team_id": t["partner_team_id"],
            "give": [t["get"][0]["id"]],
            "get": [t["give"][0]["id"]],
        },
    )
    assert r.status_code == 422


def test_chat_history_empty_for_new_conversation(api):
    assert api.get(f"/api/leagues/{api.league_id}/chat/00000000-0000").json() == []
