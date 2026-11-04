#!/usr/bin/env bash
# Work around broken platform.mac_ver() on some macOS builds (pip truststore crash).
export PIP_USE_TRUSTSTORE=false
export MACOSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-14.0}"
