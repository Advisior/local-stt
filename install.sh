#!/bin/bash
# Local-STT one-command installer.
#
#   curl -fsSL https://raw.githubusercontent.com/Advisior/local-stt/main/install.sh | bash
#
# Sets up a self-contained Python environment, builds the native menu bar app
# from source, and installs it to /Applications. Only ever touches:
#   ~/Library/Application Support/Local-STT/   (Python venv + source checkout)
#   /Applications/Local-STT.app
set -euo pipefail

# --prefix is a testing escape hatch: it lets this script be exercised against
# a throwaway directory instead of the real install location. The built app
# only auto-discovers Python at the default location below, so a custom
# --prefix is for testing this installer, not a supported end-user setting.
PREFIX="$HOME/Library/Application Support/Local-STT"
BUILD_ONLY=0
LOGIN_ITEM=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix)
            PREFIX="$2"
            shift 2
            ;;
        --build-only)
            BUILD_ONLY=1
            shift
            ;;
        --login-item)
            LOGIN_ITEM="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

echo "Local-STT installer"
echo "===================="

# 1. Platform preflight
if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "ERROR: Local-STT only runs on macOS." >&2
    exit 1
fi
if [[ "$(uname -m)" != "arm64" ]]; then
    echo "ERROR: Local-STT requires Apple Silicon (M1 or later)." >&2
    echo "MLX Whisper runs on the Apple GPU; there is no Intel build." >&2
    exit 1
fi

# 2. Swift toolchain (ships with Xcode Command Line Tools)
if ! command -v swift >/dev/null 2>&1; then
    echo "ERROR: Swift toolchain not found." >&2
    echo "Run: xcode-select --install" >&2
    echo "Then re-run this installer." >&2
    exit 1
fi

# 3. Python: prefer uv, else a system Python in the supported range
USE_UV=0
PYTHON_BIN=""

find_system_python() {
    for candidate in python3.12 python3.13 python3.11; do
        if command -v "$candidate" >/dev/null 2>&1; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

if command -v uv >/dev/null 2>&1; then
    USE_UV=1
elif PYTHON_BIN="$(find_system_python)"; then
    :
elif command -v brew >/dev/null 2>&1; then
    echo "No uv or Python 3.11-3.13 found. Installing uv via Homebrew..."
    brew install uv
    USE_UV=1
else
    echo "ERROR: need either 'uv' or a system Python 3.11-3.13, and Homebrew isn't installed to fetch one automatically." >&2
    echo "Install Homebrew first: https://brew.sh" >&2
    echo "Or install uv directly: https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
fi

mkdir -p "$PREFIX"

# 4. Locate or fetch the source checkout
REPO_DIR=""
SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
if [[ -n "$SCRIPT_SOURCE" && -f "$SCRIPT_SOURCE" ]]; then
    CANDIDATE_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"
    if [[ -f "$CANDIDATE_DIR/pyproject.toml" ]] && grep -q '^name = "local-stt"' "$CANDIDATE_DIR/pyproject.toml"; then
        REPO_DIR="$CANDIDATE_DIR"
        echo "Using local checkout: $REPO_DIR"
    fi
fi

if [[ -z "$REPO_DIR" ]]; then
    REPO_DIR="$PREFIX/src"
    if [[ -d "$REPO_DIR/.git" ]]; then
        echo "Updating existing checkout at $REPO_DIR..."
        git -C "$REPO_DIR" fetch --depth 1 origin main
        git -C "$REPO_DIR" reset --hard origin/main
    else
        echo "Cloning local-stt into $REPO_DIR..."
        rm -rf "$REPO_DIR"
        git clone --depth 1 --branch main https://github.com/Advisior/local-stt.git "$REPO_DIR"
    fi
fi

# 5. Python environment. Non-editable install: the venv must keep working even
# if the source checkout is later removed.
VENV_DIR="$PREFIX/venv"
echo "Creating Python environment at $VENV_DIR..."
rm -rf "$VENV_DIR"

if [[ "$USE_UV" == "1" ]]; then
    uv venv "$VENV_DIR" --python 3.12
    uv pip install --python "$VENV_DIR/bin/python" "$REPO_DIR[mlx,macos]"
else
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --upgrade pip
    "$VENV_DIR/bin/pip" install "$REPO_DIR[mlx,macos]"
fi

# 6. Build the menu bar app
echo "Building Local-STT.app..."
( cd "$REPO_DIR" && bash scripts/build-app.sh )

APP_SRC="$REPO_DIR/dist/Local-STT.app"
if [[ ! -d "$APP_SRC" ]]; then
    echo "ERROR: build did not produce $APP_SRC" >&2
    exit 1
fi

if [[ "$BUILD_ONLY" == "1" ]]; then
    echo ""
    echo "Built (not installed): $APP_SRC"
    exit 0
fi

# 7. Install to /Applications
APP_DEST="/Applications/Local-STT.app"
if [[ -d "$APP_DEST" ]]; then
    echo "Removing previous installation..."
    rm -rf "$APP_DEST"
fi
cp -R "$APP_SRC" "$APP_DEST"
xattr -cr "$APP_DEST" 2>/dev/null || true
echo "Installed: $APP_DEST"

# 8. Login Items
add_login_item=""
if [[ "$LOGIN_ITEM" == "yes" ]]; then
    add_login_item="y"
elif [[ "$LOGIN_ITEM" == "no" ]]; then
    add_login_item="n"
elif [[ -r /dev/tty ]]; then
    read -rp "Add to Login Items (auto-start on login)? [Y/n] " add_login_item </dev/tty || add_login_item="n"
    add_login_item="${add_login_item:-y}"
else
    echo "Non-interactive shell: skipping Login Items. Re-run with --login-item yes to enable it."
    add_login_item="n"
fi

if [[ "$add_login_item" =~ ^[Yy]$ ]]; then
    osascript -e "
        tell application \"System Events\"
            try
                delete login item \"Local-STT\"
            end try
            make login item at end with properties {path:\"${APP_DEST}\", hidden:true}
        end tell
    "
    echo "Added to Login Items."
fi

cat <<SUMMARY

Done. Launch with: open '${APP_DEST}'

First launch: macOS will show "Local-STT" is from an unidentified developer
(this build is ad-hoc signed, not notarized). Right-click the app in
/Applications > Open > Open to bypass Gatekeeper once.

Local-STT needs three permissions on first start, granted via system dialogs:
  1. Microphone            - audio capture for speech recognition
  2. Accessibility         - global hotkey detection
  3. Input Monitoring      - keyboard event monitoring
Grant each in System Settings > Privacy & Security if the dialog doesn't
appear automatically. After granting Accessibility, restart the daemon
(Stop + Start in the menu bar) for it to take effect.
SUMMARY
