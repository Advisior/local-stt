#!/bin/bash
# Regenerate the hash-locked requirements of the standalone runtime (#63).
#
# The runtime is built on a macOS 15 runner but must run on macOS 13 (the
# daemon's minimum; the menu bar app needs 14), so the lock is resolved for
# macOS 13 on arm64.
# EXCLUDE_NEWER keeps the resolution reproducible and only takes releases
# that have been public for a while; move it forward on purpose.
#
# After a dependency change in pyproject.toml, run this and commit the result:
#   bash scripts/lock-runtime.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNTIME_DIR="$SCRIPT_DIR/runtime"
EXCLUDE_NEWER="2026-10-20"

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv is required to lock the runtime: https://docs.astral.sh/uv/" >&2
    exit 1
fi

cd "$PROJECT_DIR"
export MACOSX_DEPLOYMENT_TARGET=13.0
common=(
    --python-platform aarch64-apple-darwin
    --python-version 3.12
    --only-binary :all:
    --generate-hashes
    --exclude-newer "$EXCLUDE_NEWER"
    --custom-compile-command "bash scripts/lock-runtime.sh"
    --quiet
)
uv pip compile pyproject.toml --extra mlx --extra macos "${common[@]}" \
    -o scripts/runtime/requirements.txt
uv pip compile scripts/runtime/build-requirements.in "${common[@]}" \
    -o scripts/runtime/build-requirements.txt
echo "Locked: $RUNTIME_DIR/requirements.txt, $RUNTIME_DIR/build-requirements.txt"
