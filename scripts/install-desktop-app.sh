#!/usr/bin/env bash
# Install the Orion Mac app (native window around the local site).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# shellcheck disable=SC1091
source "$REPO_ROOT/scripts/macos_python_env.sh"
# shellcheck disable=SC1091
source "$REPO_ROOT/scripts/pip_env.sh"

if [ ! -x "$REPO_ROOT/.venv/bin/python" ]; then
  echo "Virtualenv missing. Run: bash scripts/install-mac.sh" >&2
  exit 1
fi

"$REPO_ROOT/.venv/bin/python" -m pip install -q -r "$REPO_ROOT/desktop/requirements.txt"
"$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/desktop/make_icon.py"

cc -O2 -o "$REPO_ROOT/desktop/Orion.app/Contents/MacOS/Orion" "$REPO_ROOT/desktop/stub.c"
chmod +x "$REPO_ROOT/desktop/Orion.app/Contents/MacOS/Orion" "$REPO_ROOT/desktop/Orion.app/Contents/MacOS/launch"
xattr -cr "$REPO_ROOT/desktop/Orion.app" 2>/dev/null || true

SUPPORT_DIR="${HOME}/Library/Application Support/Orion"
mkdir -p "$SUPPORT_DIR"
printf '%s\n' "$REPO_ROOT" > "$SUPPORT_DIR/repo_root"

mkdir -p "${HOME}/Applications"
ln -sfn "$REPO_ROOT/desktop/Orion.app" "${HOME}/Applications/Orion.app"

echo "Orion.app is ready."
echo "  In the project:  open \"$REPO_ROOT/desktop/Orion.app\""
echo "  In Applications: open \"$HOME/Applications/Orion.app\""
echo "Drag it to the Dock if you want it there."
echo "Opening it now…"
open "$REPO_ROOT/desktop/Orion.app"
