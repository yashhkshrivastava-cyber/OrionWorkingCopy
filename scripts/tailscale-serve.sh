#!/usr/bin/env bash
# Expose Orion over HTTPS on your tailnet (requires Tailscale app + login).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
# shellcheck disable=SC1091
source "$REPO_ROOT/scripts/tailscale_cmd.sh"

if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

# The React UI (Vite). It proxies /api to the API, so one port serves the whole app.
PORT="${ORION_FRONTEND_PORT:-5173}"

if [ -z "$TAILSCALE_BIN" ]; then
  echo "Install Tailscale first:" >&2
  echo "  brew install --cask tailscale" >&2
  echo "  open -a Tailscale   # sign in on this Mac" >&2
  exit 1
fi

if ! tailscale_cmd status --peers=false >/dev/null 2>&1; then
  echo "Tailscale is not connected. Open the Tailscale app and sign in." >&2
  exit 1
fi

if ! curl -sf "http://127.0.0.1:${PORT}/" >/dev/null; then
  echo "Orion is not running on port ${PORT}. Start it with: bash scripts/start-modern.sh" >&2
  exit 1
fi

TS_IP="$(tailscale_cmd ip -4)"
echo "Orion tailnet URLs:"
echo "  HTTP:  http://${TS_IP}:${PORT}"
DNS_NAME="$(tailscale_cmd status --json 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("Self",{}).get("DNSName","").rstrip("."))' 2>/dev/null || true)"
if [ -n "$DNS_NAME" ]; then
  echo "  HTTPS: https://${DNS_NAME}"
fi
echo ""
echo "Enabling Tailscale Serve (HTTPS on port 443)..."

tailscale_cmd serve --bg --https=443 "http://127.0.0.1:${PORT}"
tailscale_cmd serve status

echo ""
echo "Install Tailscale on phones/tablets/other Macs and open the HTTPS URL above."
