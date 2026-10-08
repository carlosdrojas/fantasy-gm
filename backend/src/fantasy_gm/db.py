"""Database engine, session factory, and ORM models.

Models are platform-agnostic: an ESPN adapter (and later Sleeper/Yahoo) maps its
payloads onto these tables, so analytics and the API never see raw ESPN shapes.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    TypeDecorator,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes, even on SQLite (which stores them naive)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC) if value is not None else None

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)  # Postgres answers in the session's time zone


class Base(DeclarativeBase):
    type_annotation_map: ClassVar = {dict[str, Any]: JSON, list[Any]: JSON}


class League(Base):
    __tablename__ = "leagues"
    __table_args__ = (UniqueConstraint("platform", "external_id", "season"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(64))
    season: Mapped[int]
    name: Mapped[str | None] = mapped_column(String)
    current_week: Mapped[int | None]
    final_regular_week: Mapped[int | None]
    my_team_id: Mapped[int | None] = mapped_column(Integer)  # Team.id, not the platform id
    # Normalized settings: lineup slot counts, scoring type, playoff teams, etc.
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # Last in-game refresh (lineups, live points, scores). Analytics are keyed on
    # last_synced_at instead, so live refreshes don't invalidate cached simulations.
    live_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    teams: Mapped[list[Team]] = relationship(back_populates="league", cascade="all, delete-orphan")


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("league_id", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String)
    abbrev: Mapped[str | None] = mapped_column(String)
    owner_name: Mapped[str | None] = mapped_column(String)
    owner_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    wins: Mapped[int] = mapped_column(default=0)
    losses: Mapped[int] = mapped_column(default=0)
    ties: Mapped[int] = mapped_column(default=0)
    points_for: Mapped[float] = mapped_column(Float, default=0.0)
    points_against: Mapped[float] = mapped_column(Float, default=0.0)
    playoff_seed: Mapped[int | None]
    waiver_rank: Mapped[int | None]
    faab_spent: Mapped[int | None]
    logo_url: Mapped[str | None] = mapped_column(String)

    league: Mapped[League] = relationship(back_populates="teams")
    roster: Mapped[list[RosterEntry]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )


class Player(Base):
    """A pro player. Keyed by platform so ids never collide across platforms."""

    __tablename__ = "players"
    __table_args__ = (UniqueConstraint("platform", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(64))
    full_name: Mapped[str] = mapped_column(String)
    position: Mapped[str] = mapped_column(String)
    pro_team: Mapped[str | None] = mapped_column(String)
    injury_status: Mapped[str | None] = mapped_column(String)
    eligible_slots: Mapped[list[Any]] = mapped_column(JSON, default=list)  # slot names
    percent_owned: Mapped[float | None] = mapped_column(Float)
    percent_owned_change: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class RosterEntry(Base):
    """Current roster snapshot: replaced wholesale for a league on every sync."""

    __tablename__ = "roster_entries"
    __table_args__ = (UniqueConstraint("team_id", "player_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    slot: Mapped[str] = mapped_column(String)
    acquisition_type: Mapped[str | None] = mapped_column(String)

    team: Mapped[Team] = relationship(back_populates="roster")
    player: Mapped[Player] = relationship()


class PlayerPoints(Base):
    """Fantasy points for a player in one league (scoring differs by league).

    ``week`` 0 holds season totals; ``kind`` is 'actual' or 'projected'.
    Rows are upserted, so history accumulates across syncs.
    """

    __tablename__ = "player_points"
    __table_args__ = (UniqueConstraint("league_id", "player_id", "season", "week", "kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id", ondelete="CASCADE"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    season: Mapped[int]
    week: Mapped[int]
    kind: Mapped[str] = mapped_column(String(10))
    points: Mapped[float] = mapped_column(Float)


class Matchup(Base):
    __tablename__ = "matchups"
    __table_args__ = (UniqueConstraint("league_id", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(64))
    week: Mapped[int] = mapped_column(index=True)
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    away_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    home_points: Mapped[float | None] = mapped_column(Float)
    away_points: Mapped[float | None] = mapped_column(Float)
    home_projected: Mapped[float | None] = mapped_column(Float)
    away_projected: Mapped[float | None] = mapped_column(Float)
    winner: Mapped[str] = mapped_column(String(12), default="UNDECIDED")  # HOME/AWAY/TIE/UNDECIDED
    is_playoff: Mapped[bool] = mapped_column(default=False)
    home_win_prob: Mapped[float | None] = mapped_column(Float)  # platform's live estimate, 0-1
    away_win_prob: Mapped[float | None] = mapped_column(Float)


class ProGame(Base):
    """One NFL game's live state. Shared by every league (it's the same NFL)."""

    __tablename__ = "pro_games"
    __table_args__ = (UniqueConstraint("external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(32))
    season: Mapped[int] = mapped_column(index=True)
    week: Mapped[int] = mapped_column(index=True)
    home_team: Mapped[str] = mapped_column(String)
    away_team: Mapped[str] = mapped_column(String)
    home_score: Mapped[int | None]
    away_score: Mapped[int | None]
    state: Mapped[str] = mapped_column(String)  # pre/in/post
    detail: Mapped[str] = mapped_column(String, default="")
    kickoff: Mapped[datetime | None] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("league_id", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"))
    week: Mapped[int | None]
    bid_amount: Mapped[int | None]
    proposed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # [{type, player_id (Player.id), from_team_id, to_team_id}]
    items: Mapped[list[Any]] = mapped_column(JSON, default=list)


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(12), default="running")  # running/ok/error
    error: Mapped[str | None] = mapped_column(String(2000))


class ChatMessage(Base):
    """One API message (user or assistant) of an assistant conversation, stored verbatim."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id", ondelete="CASCADE"), index=True)
    # Who owns the conversation; None for anonymous demo visitors.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(12))
    content: Mapped[list[Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class User(Base):
    """An account. ``external_id`` is the auth provider's user id (Clerk's ``sub``), or
    "local" for the single user of a self-hosted install without accounts."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class LeagueMember(Base):
    """A user's access to a league. Leagues are stored once and shared by their members;
    each member has their own team in it."""

    __tablename__ = "league_members"
    __table_args__ = (UniqueConstraint("user_id", "league_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id", ondelete="CASCADE"), index=True)
    my_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_viewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class EspnCredential(Base):
    """A user's ESPN session cookies, encrypted at rest (see crypto.py)."""

    __tablename__ = "espn_credentials"
    __table_args__ = (UniqueConstraint("user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    espn_s2_encrypted: Mapped[str] = mapped_column(String(2048))
    swid_encrypted: Mapped[str] = mapped_column(String(512))
    # "unverified" until a sync uses them, then "ok" or "expired" (ESPN refused them).
    status: Mapped[str] = mapped_column(String(16), default="unverified")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def init_db(database_url: str) -> Engine:
    """Create the engine and tables. Safe to call more than once (re-inits)."""
    global _engine, _session_factory
    database_url = normalize_database_url(database_url)
    if database_url.startswith("sqlite:///") and database_url != "sqlite:///:memory:":
        Path(database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    # Hosted Postgres drops idle connections (Neon scales to zero): check before use.
    _engine = create_engine(
        database_url, connect_args=connect_args, pool_pre_ping=not database_url.startswith("sqlite")
    )
    if database_url.startswith("sqlite"):

        @event.listens_for(_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    Base.metadata.create_all(_engine)
    _add_missing_columns(_engine)
    _session_factory = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def normalize_database_url(url: str) -> str:
    """Hosted Postgres (Neon, Fly) hands out ``postgres://``/``postgresql://`` URLs;
    SQLAlchemy needs the driver named to use psycopg 3."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url


def _add_missing_columns(engine: Engine) -> None:
    """Lightweight migration: add nullable columns that models gained since the DB was made.

    ``create_all`` only creates missing tables, so an existing database would otherwise
    lack new columns. Anything beyond adding a nullable column needs a real migration.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in have:
                    continue
                if not column.nullable:
                    raise RuntimeError(
                        f"Column {table.name}.{column.name} is NOT NULL; add it with a migration"
                    )
                ddl = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {ddl}'))


@contextmanager
def session_scope() -> Iterator[Session]:
    if _session_factory is None:
        raise RuntimeError("init_db() has not been called")
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
