"""Accounts: Clerk-style session tokens, per-user leagues and teams, ESPN cookies."""

import time
from datetime import timedelta
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select

from fantasy_gm import auth, chat
from fantasy_gm.api.app import create_app
from fantasy_gm.db import EspnCredential, League, LeagueMember, SyncRun, session_scope, utcnow
from tests.fake_espn import LEAGUE_ID, MY_SWID, SEASON

ISSUER = "https://test.clerk.example"
ALICE_S2 = "alice-" + "a" * 60  # ESPN cookies are long; short ones are rejected
BOB_S2 = "bob-" + "b" * 60
BOB_SWID = "{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(sub: str, *, azp: str = "https://fgm.example", ttl: int = 60, issuer: str = ISSUER):
    now = int(time.time())
    claims = {"sub": sub, "iss": issuer, "iat": now, "exp": now + ttl, "azp": azp}
    return jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": "k1"})


def as_user(sub: str) -> dict:
    return {"Authorization": f"Bearer {token(sub)}"}


ALICE, BOB = as_user("user_alice"), as_user("user_bob")


@pytest.fixture
def api(db, fake, monkeypatch):
    """A hosted setup: accounts on, demo league public, the ESPN league private."""
    jwks = SimpleNamespace(
        get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=KEY.public_key())
    )
    monkeypatch.setattr(auth, "_jwks_client", lambda issuer: jwks)
    fake.allowed_s2 = {ALICE_S2, BOB_S2}
    settings = db.model_copy(
        update={
            "auth_issuer": ISSUER,
            "auth_authorized_parties": ["https://fgm.example"],
            "secret_key": SecretStr("x" * 40),
            "demo_mode": True,
            "espn_s2": None,  # a hosted server has no cookies of its own
            "espn_swid": None,
        }
    )
    with TestClient(create_app(settings, start_scheduler=False)) as c:
        yield c


def add(api, headers):
    return api.post(
        "/api/leagues", json={"league_id": LEAGUE_ID, "season": SEASON}, headers=headers
    )


def save_cookies(api, headers, s2, swid):
    return api.put("/api/me/espn", json={"espn_s2": s2, "swid": swid}, headers=headers)


def espn_league_id(api, headers) -> int:
    return next(
        lg["id"] for lg in api.get("/api/leagues", headers=headers).json() if not lg["is_demo"]
    )


def test_anonymous_sees_only_the_demo(api):
    leagues = api.get("/api/leagues").json()
    assert [lg["is_demo"] for lg in leagues] == [True]
    assert add(api, {}).status_code == 401
    assert api.get("/api/me").json()["signed_in"] is False
    assert api.get("/api/health").json()["accounts_enabled"] is True


def test_bad_tokens_are_rejected(api):
    for headers in (
        {"Authorization": "Bearer nope"},
        {"Authorization": f"Bearer {token('u', ttl=-60)}"},  # expired
        {"Authorization": f"Bearer {token('u', issuer='https://evil.example')}"},
        {"Authorization": f"Bearer {token('u', azp='https://evil.example')}"},
        {"Authorization": f"Basic {token('u')}"},
    ):
        assert api.get("/api/leagues", headers=headers).status_code == 401, headers


def test_private_league_needs_your_own_cookies(api):
    r = add(api, ALICE)
    assert r.status_code == 403 and "private" in r.json()["detail"]

    assert save_cookies(api, ALICE, ALICE_S2, MY_SWID).status_code == 200
    r = add(api, ALICE)
    assert r.status_code == 201, r.text
    lid = r.json()["id"]
    lg = api.get(f"/api/leagues/{lid}", headers=ALICE).json()
    mine = next(t for t in lg["teams"] if t["id"] == lg["my_team_id"])
    assert mine["name"] == "Mine"  # detected from the SWID
    assert add(api, ALICE).status_code == 409

    # Knowing the league id isn't enough: Bob can't see it, or join without access.
    assert api.get(f"/api/leagues/{lid}", headers=BOB).status_code == 404
    assert api.get(f"/api/leagues/{lid}").status_code == 404
    assert add(api, BOB).status_code == 403
    save_cookies(api, BOB, "wrong-" + "c" * 60, BOB_SWID)
    assert add(api, BOB).status_code == 403
    # A failed join doesn't brand Bob's cookies expired: they may be fine elsewhere.
    assert api.get("/api/me", headers=BOB).json()["espn"]["status"] == "unverified"


def test_members_share_a_league_but_not_a_team(api):
    save_cookies(api, ALICE, ALICE_S2, MY_SWID)
    lid = add(api, ALICE).json()["id"]
    save_cookies(api, BOB, BOB_S2, BOB_SWID)
    assert add(api, BOB).json()["id"] == lid  # joined the stored league

    bob_view = api.get(f"/api/leagues/{lid}", headers=BOB).json()
    assert bob_view["my_team_id"] is None  # Bob's SWID owns no team here
    juggernaut = next(t["id"] for t in bob_view["teams"] if t["name"] == "Juggernaut")
    r = api.put(f"/api/leagues/{lid}/my-team", json={"team_id": juggernaut}, headers=BOB)
    assert r.status_code == 200
    assert api.get(f"/api/leagues/{lid}", headers=BOB).json()["my_team_id"] == juggernaut
    alice_team = api.get(f"/api/leagues/{lid}", headers=ALICE).json()["my_team_id"]
    assert alice_team not in (None, juggernaut)
    assert api.get(f"/api/leagues/{lid}/waivers", headers=BOB).json()["team_id"] == juggernaut

    # Leaving keeps the league for the other member; the last one out deletes it.
    assert api.delete(f"/api/leagues/{lid}", headers=ALICE).status_code == 204
    assert api.get(f"/api/leagues/{lid}", headers=BOB).status_code == 200
    assert api.delete(f"/api/leagues/{lid}", headers=BOB).status_code == 204
    with session_scope() as s:
        assert s.get(League, lid) is None


def test_cookies_are_encrypted_at_rest(api):
    save_cookies(api, ALICE, ALICE_S2, MY_SWID)
    with session_scope() as s:
        cred = s.scalar(select(EspnCredential))
        assert ALICE_S2 not in cred.espn_s2_encrypted
        assert MY_SWID not in cred.swid_encrypted
    assert save_cookies(api, ALICE, ALICE_S2, "not-a-swid").status_code == 422


def test_expired_cookies_are_flagged(api, fake):
    save_cookies(api, ALICE, ALICE_S2, MY_SWID)
    lid = add(api, ALICE).json()["id"]
    assert api.get("/api/me", headers=ALICE).json()["espn"]["status"] == "ok"

    fake.allowed_s2 = set()  # ESPN stops accepting Alice's cookies
    with session_scope() as s:
        s.get(League, lid).last_synced_at = utcnow() - timedelta(hours=1)
    assert api.post(f"/api/leagues/{lid}/sync", headers=ALICE).status_code == 401
    assert api.get("/api/me", headers=ALICE).json()["espn"]["status"] == "expired"


def test_manual_sync_has_a_cooldown(api):
    save_cookies(api, ALICE, ALICE_S2, MY_SWID)
    lid = add(api, ALICE).json()["id"]
    assert api.post(f"/api/leagues/{lid}/sync", headers=ALICE).status_code == 429


def test_opening_a_stale_league_syncs_it(api):
    save_cookies(api, ALICE, ALICE_S2, MY_SWID)
    lid = add(api, ALICE).json()["id"]
    with session_scope() as s:
        s.get(League, lid).last_synced_at = utcnow() - timedelta(hours=2)
        runs = s.scalar(select(func.count()).select_from(SyncRun).where(SyncRun.league_id == lid))
    assert api.get(f"/api/leagues/{lid}", headers=ALICE).json()["syncing"] is True
    for _ in range(100):
        with session_scope() as s:
            done = s.scalar(
                select(func.count()).where(SyncRun.league_id == lid, SyncRun.status == "ok")
            )
        if done > runs:
            break
        time.sleep(0.05)
    else:
        pytest.fail("background sync didn't finish")
    with session_scope() as s:
        m = s.scalar(select(LeagueMember).where(LeagueMember.league_id == lid))
        assert m.last_viewed_at is not None


def test_conversations_are_private(api):
    save_cookies(api, ALICE, ALICE_S2, MY_SWID)
    lid = add(api, ALICE).json()["id"]
    save_cookies(api, BOB, BOB_S2, BOB_SWID)
    add(api, BOB)
    me = api.get("/api/me", headers=ALICE)  # creates nothing; just resolves Alice
    assert me.json()["signed_in"]
    with session_scope() as s:
        alice_id = s.scalar(select(LeagueMember.user_id).where(LeagueMember.league_id == lid))
    chat._save(chat.Conversation(lid, "c-1", alice_id), "user", [{"type": "text", "text": "hi"}])
    assert api.get(f"/api/leagues/{lid}/chat/c-1", headers=ALICE).json() == [
        {"role": "user", "text": "hi"}
    ]
    assert api.get(f"/api/leagues/{lid}/chat/c-1", headers=BOB).json() == []


def test_chat_never_spends_the_servers_key(api):
    save_cookies(api, ALICE, ALICE_S2, MY_SWID)
    lid = add(api, ALICE).json()["id"]
    r = api.post(f"/api/leagues/{lid}/chat", json={"message": "hi"}, headers=ALICE)
    assert r.status_code == 401


def test_demo_league_stays_read_only(api):
    demo_id = api.get("/api/leagues").json()[0]["id"]
    assert api.get(f"/api/leagues/{demo_id}", headers=ALICE).status_code == 200
    for method, path in (("post", "/sync"), ("delete", ""), ("put", "/my-team")):
        kwargs = {"json": {"team_id": None}} if method == "put" else {}
        r = getattr(api, method)(f"/api/leagues/{demo_id}{path}", headers=ALICE, **kwargs)
        assert r.status_code == 403, (method, path)


def test_league_limit(api):
    save_cookies(api, ALICE, ALICE_S2, MY_SWID)
    with session_scope() as s:
        uid = auth.user_id_for("user_alice")
        for i in range(12):
            lg = League(platform="espn", external_id=f"x{i}", season=SEASON, settings={})
            s.add(lg)
            s.flush()
            s.add(LeagueMember(user_id=uid, league_id=lg.id))
    r = add(api, ALICE)
    assert r.status_code == 400 and "up to 12" in r.json()["detail"]


def test_deleting_an_account_removes_everything(api):
    save_cookies(api, ALICE, ALICE_S2, MY_SWID)
    lid = add(api, ALICE).json()["id"]
    assert api.delete("/api/me", headers=ALICE).status_code == 204
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(EspnCredential)) == 0
        assert s.get(League, lid) is None
