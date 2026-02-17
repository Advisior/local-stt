#!/bin/bash
# Install Local-STT.app to /Applications and optionally add to Login Items
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_NAME="Local-STT"
SOURCE="$PROJECT_DIR/dist/${APP_NAME}.app"
DEST="/Applications/${APP_NAME}.app"

# Build first if needed
if [[ ! -d "$SOURCE" ]]; then
    echo "Building app first..."
    bash "$SCRIPT_DIR/build-app.sh"
fi

# Install
if [[ -d "$DEST" ]]; then
    echo "Removing previous installation..."
    rm -rf "$DEST"
fi

cp -R "$SOURCE" "$DEST"
echo "Installed: $DEST"

# Add to Login Items
read -rp "Add to Login Items (auto-start on login)? [Y/n] " answer
answer="${answer:-Y}"

if [[ "$answer" =~ ^[Yy]$ ]]; then
    osascript -e "
        tell application \"System Events\"
            try
                delete login item \"${APP_NAME}\"
            end try
            make login item at end with properties {path:\"${DEST}\", hidden:true}
        end tell
    "
    echo "Added to Login Items."
fi

echo ""
echo "Done! Launch with: open '${DEST}'"
