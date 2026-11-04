#!/usr/bin/env bash
# Start the Orion React frontend (Vite dev server).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT/frontend"

export PATH="/opt/homebrew/bin:${PATH}"

if ! command -v npm >/dev/null 2>&1; then
  echo "Node.js/npm required. Install with: brew install node" >&2
  exit 1
fi

if [ ! -d node_modules ]; then
  npm install
fi

echo "Starting Orion frontend on http://localhost:5173 (also reachable on your Tailscale IP)"
exec npm run dev
