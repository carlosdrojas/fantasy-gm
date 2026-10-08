import httpx
import pytest

from fantasy_gm.espn.client import EspnAuthError, EspnClient, EspnError, EspnNotFoundError
from tests.fake_espn import LEAGUE_ID, SEASON


def test_happy_path_sends_views_and_cookies(client, fake):
    data = client.league(LEAGUE_ID, SEASON, ["mTeam", "mSettings"])
    assert data["settings"]["name"] == "Test League"
    req = fake.calls[-1]
    assert req.url.params.get_list("view") == ["mTeam", "mSettings"]
    assert "espn_s2=s2" in req.headers["cookie"]


@pytest.mark.parametrize("status", [401, 403])
def test_auth_errors(client, fake, status):
    fake.fail_with = [status]
    with pytest.raises(EspnAuthError, match="cookies"):
        client.league(LEAGUE_ID, SEASON, ["mTeam"])


def test_not_found(client):
    with pytest.raises(EspnNotFoundError):
        client.league("999", SEASON, ["mTeam"])


def test_login_page_html_is_auth_error():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text="<html>login</html>"))
    with pytest.raises(EspnAuthError, match="non-JSON"):
        EspnClient(transport=transport).league(LEAGUE_ID, SEASON, ["mTeam"])


def test_retries_transient_then_succeeds(client, fake):
    fake.fail_with = [503, 429]
    assert client.league(LEAGUE_ID, SEASON, ["mSettings"])["settings"]
    assert len(fake.calls) == 3


def test_gives_up_after_repeated_5xx(client, fake):
    fake.fail_with = [500] * 10
    with pytest.raises(EspnError):
        client.league(LEAGUE_ID, SEASON, ["mSettings"])
    assert len(fake.calls) == 4


def test_filter_header(client, fake):
    client.free_agents(LEAGUE_ID, SEASON, scoring_period=4, limit=10)
    assert '"limit": 10' in fake.calls[-1].headers["X-Fantasy-Filter"]
