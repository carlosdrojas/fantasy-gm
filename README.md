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
| `fgm demo` | Add (or rebuild) the made-up demo league. No ESPN access needed |

## Demo mode

`FGM_DEMO_MODE=true` turns the backend into a public, read-only demo. It serves only a
made-up 10-team league, "Gridiron Think Tank", which is rebuilt on every start. Adding,
deleting and syncing leagues returns 403, background sync doesn't run, and no ESPN cookies
or API keys are needed. The Assistant's question menu works as usual. Claude chat runs only
on an Anthropic key the visitor adds; the server's key is never used.

The demo league uses **real NFL players and their real weekly fantasy points** (PPR, from
ESPN) from `backend/src/fantasy_gm/demo/pool.json`. **The teams, managers, draft, waiver
claims and schedule are made up.** A seeded simulation drafts the teams, sets lineups,
makes claims and scores each week from the starters' real points, so the league comes out
the same on every build. The demo user manages "Fourth & Long Shots": 1–3 despite the
third-strongest roster.

```bash
FGM_DATABASE_URL=sqlite:///$PWD/backend/data/demo.db FGM_DEMO_MODE=true API_PORT=8766 WEB_PORT=3001 ./dev.sh
```

To refresh the player pool for a newer week (needs ESPN cookies and a league you can read):
`cd backend && .venv/bin/python scripts/export_demo_pool.py <espn_league_id> --week 6`.

## Deploying the demo

The backend runs as one always-on container (`backend/Dockerfile`, demo mode by default).
It needs no disk, because the demo league is rebuilt on every start. The Next.js frontend
calls it from the server, so visitors never talk to the backend directly.

1. **Backend on Fly.io** (Railway and Render also run the same Dockerfile):
   ```bash
   cd backend
   fly launch --no-deploy --internal-port 8000   # pick an app name, decline the databases
   fly deploy
   curl https://<app>.fly.dev/api/health       # {"ok":true,"demo_mode":true,...}
   ```
2. **Frontend on Vercel**: import the GitHub repo, set the root directory to `frontend`,
   and add the environment variable `FGM_API_URL=https://<app>.fly.dev`. Optionally set
   `FGM_REPO_URL` (where the banner and header link; defaults to this repo).

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
- **Assistant**: two modes. A menu of 8 questions (lineup, waivers, trades, weak spots,
  odds, luck, matchup, the team to beat) is answered instantly from the analytics with
  fixed templates: no model, no key, the same answer every time. Free-form chat is
  Claude Opus 5 with read-only tools over the same analytics (rosters, waivers, trade
  search and evaluation, odds, transactions). It uses the server's key, or a key you
  add in the browser; that key is stored in the browser only and sent with each message.
  Conversations are saved in the database.
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
