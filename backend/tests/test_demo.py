import pytest
from fastapi.testclient import TestClient

from fantasy_gm import demo
from fantasy_gm.api.app import create_app
from fantasy_gm.db import init_db
from tests.fake_espn import LEAGUE_ID, SEASON


def test_build_is_deterministic():
    a, b = demo.build_snapshot(), demo.build_snapshot()
    assert [(t.name, t.wins, t.points_for, t.roster) for t in a.teams] == [
        (t.name, t.wins, t.points_for, t.roster) for t in b.teams
    ]
    assert [(m.home_points, m.away_points) for m in a.matchups] == [
        (m.home_points, m.away_points) for m in b.matchups
    ]


def test_league_is_consistent():
    snap = demo.build_snapshot()
    players = {p.external_id: p for p in snap.players}
    rostered = [r.player_external_id for t in snap.teams for r in t.roster]
    assert len(snap.teams) == 10
    assert len(rostered) == len(set(rostered)), "a player is on two teams"
    assert all(len(t.roster) == demo.ROUNDS for t in snap.teams)

    starting = {s: n for s, n in demo.SLOT_COUNTS.items() if s not in ("BE", "IR")}
    for t in snap.teams:
        slots = [r.slot for r in t.roster]
        assert {s: slots.count(s) for s in starting} == starting, t.name
        for r in t.roster:
            assert r.slot in [*players[r.player_external_id].eligible_slots, "BE", "IR"]

    # Records add up to the completed weeks, and points-for to the scored matchups.
    done = [m for m in snap.matchups if m.week < snap.current_week]
    assert all(m.winner != "UNDECIDED" for m in done)
    for t in snap.teams:
        assert t.wins + t.losses + t.ties == snap.current_week - 1
        pf = sum(
            m.home_points if m.home_team_external_id == t.external_id else m.away_points
            for m in done
            if t.external_id in (m.home_team_external_id, m.away_team_external_id)
        )
        assert t.points_for == pytest.approx(pf)

    for txn in snap.transactions:
        add = next(i for i in txn.items if i.type == "ADD")
        assert add.player_external_id in players


@pytest.fixture
def demo_api(db):
    """Demo mode on a database that also holds a real (ESPN) league."""
    with TestClient(create_app(db, start_scheduler=False)) as c:
        r = c.post("/api/leagues", json={"league_id": LEAGUE_ID, "season": SEASON})
        espn_league_id = r.json()["id"]
    with TestClient(create_app(db.model_copy(update={"demo_mode": True}))) as c:
        c.espn_league_id = espn_league_id
        yield c


def test_demo_mode_serves_only_the_demo_league(demo_api):
    assert demo_api.get("/api/health").json()["demo_mode"] is True
    leagues = demo_api.get("/api/leagues").json()
    assert [lg["platform"] for lg in leagues] == ["demo"]
    assert demo_api.get(f"/api/leagues/{demo_api.espn_league_id}").status_code == 404
    assert demo_api.get(f"/api/leagues/{demo_api.espn_league_id}/transactions").status_code == 404


def test_demo_mode_refuses_writes(demo_api):
    lid = demo_api.get("/api/leagues").json()[0]["id"]
    assert (
        demo_api.post("/api/leagues", json={"league_id": "1", "season": SEASON}).status_code == 403
    )
    assert demo_api.delete(f"/api/leagues/{lid}").status_code == 403
    assert demo_api.post(f"/api/leagues/{lid}/sync").status_code == 403
    assert demo_api.post(f"/api/leagues/{lid}/chat", json={"message": "hi"}).status_code == 403
    assert len(demo_api.get("/api/leagues").json()) == 1


def test_demo_league_read_endpoints(demo_api):
    lg = demo_api.get("/api/leagues").json()[0]
    lid, me = lg["id"], lg["my_team_id"]
    assert lg["my_team"]["owner_name"] == "You (demo)"
    for path in (
        "",
        "/power",
        "/positions",
        f"/teams/{me}",
        "/matchups",
        "/transactions",
        "/waivers",
        "/odds",
        "/trades",
        "/free-agents",
    ):
        r = demo_api.get(f"/api/leagues/{lid}{path}")
        assert r.status_code == 200, (path, r.text)

    trades = demo_api.get(f"/api/leagues/{lid}/trades").json()["trades"]
    assert trades, "the demo should always have trade ideas"
    t = trades[0]
    r = demo_api.post(
        f"/api/leagues/{lid}/trades/analyze",
        json={
            "partner_team_id": t["partner_team_id"],
            "give": [p["id"] for p in t["give"]],
            "get": [p["id"] for p in t["get"]],
        },
    )
    assert r.status_code == 200, r.text
    assert demo_api.get(f"/api/leagues/{lid}/waivers").json()["suggestions"]


def test_demo_league_rebuild_keeps_its_id(settings):
    from fantasy_gm.sync import ensure_demo_league

    init_db(settings.database_url)
    assert ensure_demo_league() == ensure_demo_league()
