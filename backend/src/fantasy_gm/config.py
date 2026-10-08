"""App settings, read from environment variables or backend/.env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_prefix="FGM_", extra="ignore", env_ignore_empty=True
    )

    database_url: str = f"sqlite:///{BACKEND_DIR / 'data' / 'fantasy_gm.db'}"

    # ESPN session cookies (shared by every private league you belong to).
    espn_s2: SecretStr | None = None
    espn_swid: str | None = None

    # Background sync interval in minutes; 0 disables the in-process scheduler.
    sync_interval_minutes: int = 60
    # While NFL games are on (or about to start), refresh lineups, live points and scores
    # this often, in seconds. Outside game windows the check is a no-op. 0 disables it.
    live_interval_seconds: int = 60

    cors_origins: list[str] = ["http://localhost:3000"]

    # Public demo: serve only the built-in made-up league. Adding, deleting and syncing
    # leagues is refused, background sync is off, and no ESPN cookies are needed.
    demo_mode: bool = False

    # Accounts. Set to your Clerk instance's Frontend API URL (e.g.
    # https://example.clerk.accounts.dev) to require sign-in for adding leagues. Unset, the
    # app is single-user and uses the ESPN cookies above.
    auth_issuer: str | None = None
    # Origins allowed to have issued a token (Clerk's ``azp`` claim), e.g. your site's URL.
    auth_authorized_parties: list[str] = []
    # Encrypts users' ESPN cookies in the database. Required when accounts are on.
    secret_key: SecretStr | None = None
    max_leagues_per_user: int = 12
    # A league is re-synced when someone opens it and its data is older than this.
    stale_after_minutes: int = 60

    # For the league assistant. Also read from the plain ANTHROPIC_API_KEY variable; if unset,
    # the Anthropic SDK falls back to its own credential chain (e.g. an `ant auth login` profile).
    @property
    def accounts_enabled(self) -> bool:
        return bool(self.auth_issuer)

    anthropic_api_key: SecretStr | None = Field(
        None, validation_alias=AliasChoices("FGM_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
