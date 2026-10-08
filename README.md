# Fantasy GM

A personal manager for your ESPN fantasy football leagues. It syncs your leagues into a local
database and shows every roster, power rankings that look past the win-loss record, positional
needs, lineup fixes and waiver pickups. It only reads from ESPN and never changes your team.

```
ESPN v3 API ─▶ espn/ adapter ─▶ platform-agnostic snapshot ─▶ SQLite (history accumulates)
                                                                  │
                                              analytics/ (lineups, power, needs, waivers)
                                                                  │
                                              FastAPI  ─▶  Next.js dashboard
```

## Quick start

```bash
./dev.sh
```

The first run installs everything, creates `backend/.env`, and stops so you can fill it in:

| Variable | Where to get it |
|---|---|
| `FGM_ESPN_S2`, `FGM_ESPN_SWID` | fantasy.espn.com → DevTools → Application → Cookies → `https://fantasy.espn.com`. Copy the raw values and keep the `{}` on SWID. |
| `ANTHROPIC_API_KEY` | console.anthropic.com → API keys (only needed for the Assistant tab) |

Run `./dev.sh` again and open http://localhost:3000. From the home page, add your league
using the number after `leagueId=` in its ESPN URL. Ctrl+C stops everything.

ESPN cookies expire every few weeks. When a sync fails with an auth error, paste in fresh
cookies and restart. The backend runs on port 8765 by default (`API_PORT=… ./dev.sh` changes it).

<details><summary>Running the pieces separately</summary>

```bash
cd backend && .venv/bin/fgm serve --port 8765
cd frontend && FGM_API_URL=http://127.0.0.1:8765 pnpm dev
```
</details>

## CLI

| Command | What it does |
|---|---|
| `fgm add <id> [--season 2026]` | Import a league |
| `fgm leagues` | List imported leagues |
| `fgm sync [league#]` | Re-sync one or all leagues |
| `fgm serve [--port] [--reload]` | Run the API with background sync |

## How the numbers work

- **Player value** is expected points per game. It blends ESPN's season projection with the
  average of the last 4 games played (byes and zeros excluded). The more games played, the
  more weight recent production gets.
- **Optimal lineup** is solved exactly as an assignment problem, so FLEX and superflex slots
  are filled correctly. Players who are out never start.
- **All-play / expected wins / luck**: every team plays every other team every week. Luck is
  actual wins minus expected wins.
- **Power score (0–100)**: 45% all-play win rate, 25% scoring over the last 3 weeks, and 30%
  roster strength (the season-long optimal lineup). Preseason it uses roster strength only.
- **Positional strength**: points per game from each team's starters at a position, plus
  25% of their best backup, compared across the league as a z-score. A z-score of −0.5 or
  lower is a need; +0.5 or higher means the team is deep there.
- **Trades**: searches 1-for-1 through 2-for-2 trades with every team. Your gain is the
  change in your lineup's points per week, plus a little bench depth. Trades that hurt the
  other team are allowed. Each trade gets an acceptance estimate, mostly based on raw
  player value (what the other manager sees) and partly on lineup fit. Asks that are 4+
  points/game lopsided are dropped. You can sort by balanced (gain × acceptance), best for
  me, or most likely.
- **Playoff odds**: 5,000 simulated seasons. Weekly scores are normally distributed around
  a blend of points scored so far and current roster strength, with the league's pooled
  variance. The live week uses ESPN's projections. Playoffs are a single-elimination bracket
  with byes for top seeds. The trade analyzer re-runs the simulation with both post-trade
  rosters.
- **Assistant**: Claude Opus 5 with read-only tools over the same analytics (rosters,
  waivers, trade search and evaluation, odds, transactions). Conversations are saved
  in the database.
- **Waivers**: every free agent is tested in your lineup. Weekly gain is how much your
  season-long lineup improves; This wk uses this week's projections. Each suggestion names
  your lowest-value bench player as the drop.

## Development

```bash
cd backend && .venv/bin/pytest && .venv/bin/ruff check src tests
cd frontend && pnpm lint && pnpm build
```

The tests use a fake ESPN server (`backend/tests/fake_espn.py`), so no network access or
cookies are needed.
