"""Command line: `fgm add <league_id>`, `fgm sync`, `fgm serve`, `fgm leagues`, `fgm demo`."""

from __future__ import annotations

import logging
from datetime import date

import typer
from sqlalchemy import select

from fantasy_gm.config import get_settings
from fantasy_gm.db import League, init_db, session_scope
from fantasy_gm.espn.client import EspnError
from fantasy_gm.sync import add_espn_league, ensure_demo_league, sync_league

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def _setup(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING)
    init_db(get_settings().database_url)


@app.command()
def add(league_id: str, season: int = typer.Option(date.today().year)) -> None:
    """Add an ESPN league (the number after leagueId= in its URL) and sync it."""
    try:
        new_id = add_espn_league(league_id, season, get_settings())
    except EspnError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1) from e
    typer.secho(f"Added league {league_id} ({season}) as #{new_id}", fg="green")


@app.command()
def demo() -> None:
    """Add (or rebuild) the made-up demo league. Needs no ESPN access."""
    new_id = ensure_demo_league()
    typer.secho(f"Demo league ready as #{new_id}", fg="green")


@app.command()
def leagues() -> None:
    """List stored leagues."""
    with session_scope() as s:
        for lg in s.scalars(select(League).order_by(League.id)):
            typer.echo(
                f"#{lg.id}  {lg.name}  espn:{lg.external_id}  {lg.season}  week {lg.current_week}  synced {lg.last_synced_at}"
            )


@app.command()
def sync(league: int | None = typer.Argument(None, help="League # (default: all)")) -> None:
    """Re-sync one league or all of them."""
    with session_scope() as s:
        ids = [league] if league else list(s.scalars(select(League.id)))
    failed = False
    for lid in ids:
        try:
            run = sync_league(lid, get_settings())
            typer.secho(f"League #{lid}: {run.status}", fg="green")
        except Exception as e:
            failed = True
            typer.secho(f"League #{lid}: {e}", fg="red", err=True)
    raise typer.Exit(1 if failed else 0)


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    """Run the API (with background sync)."""
    import uvicorn

    uvicorn.run("fantasy_gm.api.app:app_factory", factory=True, host=host, port=port, reload=reload)
