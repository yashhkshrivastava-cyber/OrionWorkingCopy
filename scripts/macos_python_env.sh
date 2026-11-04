#!/usr/bin/env bash
# Work around Homebrew Python pyexpat vs system libexpat on newer macOS.
if command -v brew >/dev/null 2>&1; then
  EXPAT_PREFIX="$(brew --prefix expat 2>/dev/null || true)"
  if [ -n "$EXPAT_PREFIX" ] && [ -d "$EXPAT_PREFIX/lib" ]; then
    export DYLD_LIBRARY_PATH="$EXPAT_PREFIX/lib${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
  fi
fi
