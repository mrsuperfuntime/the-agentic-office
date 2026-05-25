#!/usr/bin/env bash
# Start THE RESEARCHER manually (without systemd)
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$PROJECT_DIR/venv/bin/activate"

[[ -f "$VENV" ]] || { echo "Run 'bash scripts/install.sh' first"; exit 1; }
[[ -f "$PROJECT_DIR/.env" ]] || { echo ".env not found — copy .env.example to .env and fill in credentials"; exit 1; }

source "$VENV"
cd "$PROJECT_DIR"

# Read HOST/PORT from .env, fall back to safe defaults
HOST="$(grep -E '^HOST=' .env 2>/dev/null | cut -d= -f2 | tr -d ' ' || echo '127.0.0.1')"
PORT="$(grep -E '^PORT=' .env 2>/dev/null | cut -d= -f2 | tr -d ' ' || echo '8009')"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8009}"

echo "Starting THE RESEARCHER on http://${HOST}:${PORT}/ui"
exec uvicorn main:app --host "$HOST" --port "$PORT"
