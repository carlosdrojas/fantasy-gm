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

    # For the league assistant. Also read from the plain ANTHROPIC_API_KEY variable; if unset,
    # the Anthropic SDK falls back to its own credential chain (e.g. an `ant auth login` profile).
    anthropic_api_key: SecretStr | None = Field(
        None, validation_alias=AliasChoices("FGM_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
