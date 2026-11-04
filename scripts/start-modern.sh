#!/usr/bin/env bash
# Start both Orion API and React frontend.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cleanup() {
  kill "$API_PID" "$FE_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

bash "$REPO_ROOT/scripts/start-api.sh" &
API_PID=$!

sleep 2
bash "$REPO_ROOT/scripts/start-frontend.sh" &
FE_PID=$!

echo ""
echo "Orion modern stack running:"
echo "  Frontend: http://localhost:5173"
echo "  API:      http://127.0.0.1:${ORION_API_PORT:-8000}"
echo "Press Ctrl+C to stop both."

wait
