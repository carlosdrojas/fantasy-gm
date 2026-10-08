#!/usr/bin/env bash
# Start Fantasy GM: backend API (with background sync) + dashboard. Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")"

API_PORT="${API_PORT:-8765}"
WEB_PORT="${WEB_PORT:-3000}"

if [ ! -x backend/.venv/bin/fgm ]; then
  echo "→ Setting up Python environment (first run)…"
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -q -e 'backend[dev]'
fi
if [ ! -d frontend/node_modules ]; then
  echo "→ Installing frontend dependencies (first run)…"
  (cd frontend && pnpm install)
fi
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  echo "→ Created backend/.env. Add your ESPN cookies and Anthropic API key there, then re-run."
  exit 1
fi

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

(cd backend && exec .venv/bin/fgm serve --port "$API_PORT") &
pids+=($!)
(cd frontend && FGM_API_URL="http://127.0.0.1:$API_PORT" exec pnpm dev -p "$WEB_PORT") &
pids+=($!)

echo "→ Fantasy GM running at http://localhost:$WEB_PORT (API on :$API_PORT)"
wait
