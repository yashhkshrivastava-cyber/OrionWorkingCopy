#!/usr/bin/env bash
# Resolve the tailscale CLI (Homebrew installs to PATH; App Store/cask does not).
if command -v tailscale >/dev/null 2>&1; then
  TAILSCALE_BIN="tailscale"
elif [ -x "/Applications/Tailscale.app/Contents/MacOS/Tailscale" ]; then
  TAILSCALE_BIN="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
else
  TAILSCALE_BIN=""
fi

tailscale_cmd() {
  if [ -z "$TAILSCALE_BIN" ]; then
    return 127
  fi
  "$TAILSCALE_BIN" "$@"
}
