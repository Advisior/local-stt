#!/bin/bash
# Run `swift <args>` in the current directory. If the default SDK lacks the
# SwiftUI macro plugin (Command Line Tools with a newer macOS SDK) and the
# 26.5 SDK is installed, retry once with SDKROOT set to it. An SDKROOT from
# the environment always wins and is used as is.
set -uo pipefail

FALLBACK_SDK="${LOCAL_STT_FALLBACK_SDK:-/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk}"

if [[ -n "${SDKROOT:-}" ]]; then
    exec swift "$@"
fi

LOG="$(mktemp)"
trap 'rm -f "$LOG"' EXIT

if swift "$@" >"$LOG" 2>&1; then
    tail -5 "$LOG"
    exit 0
fi

if grep -q "plugin for module 'SwiftUIMacros' not found" "$LOG" && [[ -d "$FALLBACK_SDK" ]]; then
    echo "Default SDK lacks the SwiftUI macro plugin, retrying with SDKROOT=$FALLBACK_SDK"
    SDKROOT="$FALLBACK_SDK" swift "$@" 2>&1 | tail -5
    exit "${PIPESTATUS[0]}"
fi

cat "$LOG"
exit 1
