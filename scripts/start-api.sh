#!/usr/bin/env bash
# Start the Orion FastAPI backend.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
# shellcheck disable=SC1091
source "$REPO_ROOT/scripts/macos_python_env.sh"
# shellcheck disable=SC1091
source "$REPO_ROOT/scripts/pip_env.sh"

if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if ! pg_isready -h "${ORION_DB_HOST:-localhost}" -p "${ORION_DB_PORT:-5432}" -q 2>/dev/null; then
  echo "PostgreSQL is not running. Start it with: brew services start postgresql@18" >&2
  exit 1
fi

VENV="${REPO_ROOT}/.venv"
if [ ! -x "$VENV/bin/python" ]; then
  echo "Virtualenv missing. Run: bash scripts/install-mac.sh" >&2
  exit 1
fi

"$VENV/bin/python" -m pip install -q -r backend/requirements.txt -c backend/constraints.txt

PORT="${ORION_API_PORT:-8000}"
echo "Starting Orion API on http://127.0.0.1:${PORT}"
exec "$VENV/bin/python" -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port "$PORT" --reload
