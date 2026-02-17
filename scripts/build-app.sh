#!/bin/bash
# Build Local-STT.app — native Swift menu bar app
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SWIFT_DIR="$PROJECT_DIR/menubar-app"
VENV_DIR="$PROJECT_DIR/.venv"

VERSION=$("$VENV_DIR/bin/python" -c "from claude_stt import __version__; print(__version__)" 2>/dev/null || echo "0.1.0")

APP_NAME="Local-STT"
DIST_DIR="$PROJECT_DIR/dist"
APP_DIR="$DIST_DIR/${APP_NAME}.app"
BINARY_NAME="ClaudeSTTMenubar"

echo "Building ${APP_NAME} v${VERSION}..."

# 1. Build Swift binary
echo "Compiling Swift..."
cd "$SWIFT_DIR"
swift build -c release 2>&1 | tail -5

BINARY="$SWIFT_DIR/.build/release/$BINARY_NAME"
if [[ ! -f "$BINARY" ]]; then
    echo "ERROR: Build failed"
    exit 1
fi

# 2. Create .app bundle
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"

# 3. Copy binary
cp "$BINARY" "$APP_DIR/Contents/MacOS/$APP_NAME"

# 3b. Copy bundled resources
# Copy any SPM resource bundles (name varies by SPM)
for bundle in "$SWIFT_DIR/.build/release/"*.bundle; do
    if [[ -d "$bundle" ]]; then
        cp -R "$bundle" "$APP_DIR/Contents/Resources/"
    fi
done
# Also copy logo directly for fallback
if [[ -f "$SWIFT_DIR/Sources/Resources/advisior_logo.png" ]]; then
    cp "$SWIFT_DIR/Sources/Resources/advisior_logo.png" "$APP_DIR/Contents/Resources/"
fi

# 4. Info.plist
cat > "$APP_DIR/Contents/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Local-STT</string>
    <key>CFBundleDisplayName</key>
    <string>Local-STT</string>
    <key>CFBundleIdentifier</key>
    <string>com.local-stt.menubar</string>
    <key>CFBundleVersion</key>
    <string>${VERSION}</string>
    <key>CFBundleShortVersionString</key>
    <string>${VERSION}</string>
    <key>CFBundleExecutable</key>
    <string>${APP_NAME}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSMicrophoneUsageDescription</key>
    <string>Local-STT needs microphone access for speech-to-text transcription.</string>
</dict>
</plist>
PLIST

echo ""
echo "Built: $APP_DIR (v${VERSION})"
echo "Install: ./scripts/install-app.sh"
