"""Platform-agnostic snapshot a platform adapter produces and the sync layer stores.

Ids here are the *platform's* ids (strings); the sync layer maps them to DB ids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass
class PlayerData:
    external_id: str
    full_name: str
    position: str
    pro_team: str | None = None
    injury_status: str | None = None
    eligible_slots: list[str] = field(default_factory=list)
    percent_owned: float | None = None
    percent_owned_change: float | None = None
    # (week, kind) -> points; week 0 = season total, kind in {"actual", "projected"}
    points: dict[tuple[int, str], float] = field(default_factory=dict)


@dataclass
class RosterSlotData:
    player_external_id: str
    slot: str
    acquisition_type: str | None = None


@dataclass
class TeamData:
    external_id: str
    name: str
    abbrev: str | None = None
    owner_name: str | None = None
    owner_ids: list[str] = field(default_factory=list)
    wins: int = 0
    losses: int = 0
    ties: int = 0
    points_for: float = 0.0
    points_against: float = 0.0
    playoff_seed: int | None = None
    waiver_rank: int | None = None
    faab_spent: int | None = None
    logo_url: str | None = None
    roster: list[RosterSlotData] = field(default_factory=list)


@dataclass
class MatchupData:
    external_id: str
    week: int
    home_team_external_id: str
    away_team_external_id: str | None
    home_points: float | None
    away_points: float | None
    home_projected: float | None
    away_projected: float | None
    winner: str
    is_playoff: bool
    home_win_prob: float | None = None  # ESPN's live win probability, 0-1
    away_win_prob: float | None = None


@dataclass
class ProGameData:
    """One NFL game. ``state`` is 'pre', 'in' or 'post'; teams use fantasy abbreviations."""

    external_id: str
    season: int
    week: int
    home_team: str
    away_team: str
    home_score: int | None
    away_score: int | None
    state: str
    detail: str  # e.g. "Final", "Q3 4:12", "9/28 - 8:15 PM EDT"
    kickoff: datetime | None


@dataclass
class TransactionItemData:
    type: str
    player_external_id: str | None
    from_team_external_id: str | None
    to_team_external_id: str | None


@dataclass
class TransactionData:
    external_id: str
    type: str
    status: str
    team_external_id: str | None
    week: int | None
    bid_amount: int | None
    proposed_at: datetime | None
    processed_at: datetime | None
    items: list[TransactionItemData] = field(default_factory=list)


@dataclass
class LeagueSnapshot:
    platform: str
    external_id: str
    season: int
    name: str | None
    current_week: int | None
    final_regular_week: int | None
    settings: dict[str, Any]
    my_team_external_id: str | None
    teams: list[TeamData]
    players: list[PlayerData]  # rostered + available players
    matchups: list[MatchupData]
    transactions: list[TransactionData]
    pro_games: list[ProGameData] = field(default_factory=list)


@dataclass
class LiveSnapshot:
    """The in-game subset of a league, refreshed often while NFL games are on."""

    platform: str
    external_id: str
    season: int
    week: int
    rosters: dict[str, list[RosterSlotData]]  # team external id -> lineup
    players: list[PlayerData]  # rostered players, with this week's live points
    matchups: list[MatchupData]
    pro_games: list[ProGameData]


class LeagueSource(Protocol):
    """What a platform adapter must provide."""

    platform: str

    def fetch_snapshot(self, external_id: str, season: int) -> LeagueSnapshot: ...
