from __future__ import annotations

import pytest
from tenacity import wait_none

from fantasy_gm import sync as sync_module
from fantasy_gm.config import Settings
from fantasy_gm.db import init_db
from fantasy_gm.espn.client import EspnClient
from tests.fake_espn import MY_SWID, FakeEspn


@pytest.fixture(autouse=True)
def _no_retry_wait():
    EspnClient._send.retry.wait = wait_none()


@pytest.fixture
def fake() -> FakeEspn:
    return FakeEspn()


@pytest.fixture
def client(fake: FakeEspn) -> EspnClient:
    return EspnClient(espn_s2="s2", swid=MY_SWID, transport=fake.transport())


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        espn_s2="s2",
        espn_swid=MY_SWID,
        sync_interval_minutes=0,
        _env_file=None,
    )


@pytest.fixture
def db(settings: Settings, fake: FakeEspn, monkeypatch) -> Settings:
    """Initialized DB with sync wired to the fake ESPN."""
    init_db(settings.database_url)
    monkeypatch.setattr(
        sync_module,
        "make_espn_client",
        lambda s: EspnClient(espn_s2="s2", swid=MY_SWID, transport=fake.transport()),
    )
    return settings
