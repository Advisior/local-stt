#!/bin/bash
# Uninstall Local-STT.app and clean up macOS permissions
set -euo pipefail

APP_NAME="Local-STT"
BUNDLE_ID="com.local-stt.menubar"
APP_PATH="/Applications/${APP_NAME}.app"
CONFIG_DIR="$HOME/.claude/plugins/claude-stt"

echo "Uninstalling ${APP_NAME}..."

# 1. Stop daemon if running
if command -v claude-stt &>/dev/null; then
    echo "Stopping daemon..."
    claude-stt stop 2>/dev/null || true
fi

# 2. Kill the menu bar app if running
pkill -x "${APP_NAME}" 2>/dev/null || true

# 3. Remove the app
if [[ -d "$APP_PATH" ]]; then
    rm -rf "$APP_PATH"
    echo "Removed ${APP_PATH}"
else
    echo "App not found at ${APP_PATH}"
fi

# 4. Clean up macOS permissions (TCC database)
echo "Cleaning up macOS permissions..."
tccutil reset Microphone "$BUNDLE_ID" 2>/dev/null || true
tccutil reset Accessibility "$BUNDLE_ID" 2>/dev/null || true
tccutil reset ListenEvent "$BUNDLE_ID" 2>/dev/null || true
tccutil reset AppleEvents "$BUNDLE_ID" 2>/dev/null || true
echo "Permissions removed from System Settings"

# 5. Remove LaunchAgent if installed
PLIST="$HOME/Library/LaunchAgents/com.claude-stt.daemon.plist"
if [[ -f "$PLIST" ]]; then
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Removed auto-start configuration"
fi

# 6. Ask about config and model data
echo ""
echo "App removed. Optional cleanup:"
echo ""
echo "  Remove config:     rm -rf ${CONFIG_DIR}"
echo "  Remove venv:       rm -rf $(dirname "$0")/../.venv"
echo "  Remove MLX models: rm -rf ~/.cache/huggingface/hub/models--mlx-community--whisper-*"
echo ""
echo "Done."
