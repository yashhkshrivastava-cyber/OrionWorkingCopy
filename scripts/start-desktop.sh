#!/usr/bin/env bash
# Open Orion in a Mac window (starts local servers if needed).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$REPO_ROOT/desktop/Orion.app/Contents/MacOS/Orion"
