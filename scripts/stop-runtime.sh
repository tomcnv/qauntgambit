#!/bin/bash
# Runtime stop script - called by control manager with TENANT_ID and BOT_ID in env

set -e

# Ensure PATH includes common PM2 install locations on both macOS and Linux.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:$PATH"
PM2="${PM2_BIN:-$(command -v pm2 || true)}"
if [ -z "$PM2" ]; then
    echo "Error: pm2 not found in PATH"
    exit 1
fi

if [ -z "$TENANT_ID" ] || [ -z "$BOT_ID" ]; then
    echo "Error: TENANT_ID and BOT_ID must be set"
    exit 1
fi

RUNTIME_NAME="runtime-${TENANT_ID}-${BOT_ID}"

if $PM2 describe "$RUNTIME_NAME" &>/dev/null; then
    echo "Stopping runtime: $RUNTIME_NAME"
    $PM2 stop "$RUNTIME_NAME"
    $PM2 delete "$RUNTIME_NAME"
    echo "Runtime $RUNTIME_NAME stopped and removed"
else
    echo "Runtime $RUNTIME_NAME not found, nothing to stop"
fi
