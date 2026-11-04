#!/usr/bin/env bash
# Bootstrap Orion on macOS (Homebrew PostgreSQL + Python venv).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
# shellcheck disable=SC1091
source "$REPO_ROOT/scripts/macos_python_env.sh"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required. Install from https://brew.sh" >&2
  exit 1
fi

if ! command -v psql >/dev/null 2>&1; then
  echo "Installing PostgreSQL..."
  brew install postgresql@18
  brew services start postgresql@18
fi

if ! python3.12 -c "import pyexpat" 2>/dev/null; then
  brew install expat python@3.12 2>/dev/null || brew install expat
  # shellcheck disable=SC1091
  source "$REPO_ROOT/scripts/macos_python_env.sh"
fi

if ! pg_isready -h localhost -p 5432 -q 2>/dev/null; then
  echo "Starting PostgreSQL..."
  brew services start postgresql@18 2>/dev/null || brew services start postgresql 2>/dev/null || true
  for _ in $(seq 1 30); do
    if pg_isready -h localhost -p 5432 -q; then break; fi
    sleep 1
  done
fi

PYTHON_BIN=""
for candidate in python3.12 python3.13 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c "import pyexpat" 2>/dev/null; then
      PYTHON_BIN="$candidate"
      break
    fi
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  echo "Installing Python 3.12 (3.14 has a broken pyexpat on some Homebrew builds)..."
  brew install python@3.12 expat
  PYTHON_BIN="$(brew --prefix python@3.12)/bin/python3.12"
  # shellcheck disable=SC1091
  source "$REPO_ROOT/scripts/macos_python_env.sh"
fi

if [ ! -x ".venv/bin/pip" ]; then
  rm -rf .venv
  "$PYTHON_BIN" -m venv .venv
elif [ ! -d ".venv" ]; then
  "$PYTHON_BIN" -m venv .venv
fi
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r backend/requirements.txt -c backend/constraints.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Created .env from .env.example — update passwords before exposing on Tailscale."
fi

set -a
# shellcheck disable=SC1091
source .env
set +a
bash "$REPO_ROOT/scripts/init_db_mac.sh"

if ! command -v tailscale >/dev/null 2>&1; then
  echo ""
  echo "Tailscale CLI not found. Install the app to reach Orion from your other devices:"
  echo "  brew install --cask tailscale"
  echo "  open -a Tailscale"
  echo "  # Sign in, then run: tailscale ip -4"
fi

echo ""
echo "Install complete. Start Orion with: bash scripts/start-modern.sh"
