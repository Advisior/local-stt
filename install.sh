#!/bin/bash
# Local-STT one-command installer.
#
#   curl -fsSL https://raw.githubusercontent.com/Advisior/local-stt/main/install.sh | bash
#
# Sets up a self-contained Python environment, installs the prebuilt menu bar
# app from the matching GitHub release (or builds it from source with
# --from-source, from a local checkout, or when the download fails), and
# installs it to /Applications. Only ever touches:
#   ~/Library/Application Support/Local-STT/   (Python venv + source checkout)
#   /Applications/Local-STT.app
set -euo pipefail

# --prefix is a testing escape hatch: it lets this script be exercised against
# a throwaway directory instead of the real install location. The built app
# only auto-discovers Python at the default location below, so a custom
# --prefix is for testing this installer, not a supported end-user setting.
PREFIX="$HOME/Library/Application Support/Local-STT"
BUILD_ONLY=0
FROM_SOURCE=0
LOGIN_ITEM=""
GITHUB_REPO="Advisior/local-stt"
BUNDLE_ID="com.local-stt.menubar"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix)
            PREFIX="$2"
            shift 2
            ;;
        --build-only)
            # Building is the point of --build-only, so it always builds.
            BUILD_ONLY=1
            FROM_SOURCE=1
            shift
            ;;
        --from-source)
            FROM_SOURCE=1
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

# 2. A local checkout (script run from disk) is development: build from source.
LOCAL_REPO_DIR=""
SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
if [[ -n "$SCRIPT_SOURCE" && -f "$SCRIPT_SOURCE" ]]; then
    CANDIDATE_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"
    if [[ -f "$CANDIDATE_DIR/pyproject.toml" ]] && grep -q '^name = "local-stt"' "$CANDIDATE_DIR/pyproject.toml"; then
        LOCAL_REPO_DIR="$CANDIDATE_DIR"
        FROM_SOURCE=1
    fi
fi

# Swift toolchain (ships with Xcode Command Line Tools). Only the source build
# needs it; the prebuilt path checks again if it has to fall back.
require_swift() {
    if ! command -v swift >/dev/null 2>&1; then
        echo "ERROR: Swift toolchain not found." >&2
        echo "Run: xcode-select --install" >&2
        echo "Then re-run this installer." >&2
        exit 1
    fi
}
if [[ "$FROM_SOURCE" == "1" ]]; then
    require_swift
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

# 4. Locate or fetch the source checkout. The remote install checks out the
# latest release tag, so the Python package matches the prebuilt app. The tag
# comes from the releases/latest redirect: no API call, no rate limit.
resolve_latest_tag() {
    local location
    location="$(curl -sI "https://github.com/$GITHUB_REPO/releases/latest" 2>/dev/null \
        | tr -d '\r' | sed -n 's|^[Ll]ocation:[[:space:]]*.*/releases/tag/||p' | head -1)" || true
    if [[ "$location" =~ ^v[0-9]+\.[0-9]+\.[0-9]+[0-9A-Za-z.+-]*$ ]]; then
        echo "$location"
    fi
}

if [[ -n "$LOCAL_REPO_DIR" ]]; then
    REPO_DIR="$LOCAL_REPO_DIR"
    echo "Using local checkout: $REPO_DIR"
else
    REPO_DIR="$PREFIX/src"
    SOURCE_REF="$(resolve_latest_tag)"
    if [[ -z "$SOURCE_REF" ]]; then
        echo "Could not resolve the latest release tag; using main."
        SOURCE_REF="main"
    fi
    if [[ -d "$REPO_DIR/.git" ]]; then
        echo "Updating existing checkout at $REPO_DIR to $SOURCE_REF..."
        git -C "$REPO_DIR" fetch --depth 1 origin "$SOURCE_REF"
        git -C "$REPO_DIR" reset --hard FETCH_HEAD
    else
        echo "Cloning local-stt $SOURCE_REF into $REPO_DIR..."
        rm -rf "$REPO_DIR"
        git clone --depth 1 --branch "$SOURCE_REF" "https://github.com/$GITHUB_REPO.git" "$REPO_DIR"
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

# 6. Get the menu bar app: the prebuilt release zip, else build from source.
VERSION="$(sed -n 's/^version[[:space:]]*=[[:space:]]*"\(.*\)"/\1/p' "$REPO_DIR/pyproject.toml" | head -1)"
DOWNLOAD_DIR=""
cleanup() {
    if [[ -n "$DOWNLOAD_DIR" ]]; then
        rm -rf "$DOWNLOAD_DIR"
    fi
}
trap cleanup EXIT

plist_value() {
    plutil -extract "$1" raw -o - "$2" 2>/dev/null || true
}

# The .sha256 file is `shasum -a 256` output: "<hex digest>  <file name>".
verify_sha256() {
    local expected="" actual=""
    read -r expected _ < "$2" || true
    actual="$(shasum -a 256 "$1" 2>/dev/null)" || return 1
    actual="${actual%% *}"
    expected="$(printf '%s' "$expected" | tr 'A-F' 'a-f')"
    [[ "$expected" =~ ^[0-9a-f]{64}$ && "$expected" == "$actual" ]]
}

# Sets APP_SRC to the unpacked, verified bundle and returns 0, or sets
# PREBUILT_REASON and returns 1. Runs in the main shell so the EXIT trap sees
# DOWNLOAD_DIR.
APP_SRC=""
PREBUILT_REASON=""
fetch_prebuilt_app() {
    local zip_name="Local-STT-v${VERSION}.zip"
    local url="https://github.com/$GITHUB_REPO/releases/download/v${VERSION}/${zip_name}"
    local http_code="" app plist bundle_id bundle_version

    if [[ -z "$VERSION" ]]; then
        PREBUILT_REASON="no version found in pyproject.toml"
        return 1
    fi
    DOWNLOAD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/local-stt-install.XXXXXX")"
    echo "Downloading prebuilt Local-STT.app v${VERSION}..."
    if ! http_code="$(curl -fsSL -o "$DOWNLOAD_DIR/$zip_name" -w '%{http_code}' "$url")"; then
        if [[ -n "$http_code" && "$http_code" != "000" ]]; then
            PREBUILT_REASON="download of $url failed with HTTP $http_code"
        else
            PREBUILT_REASON="download of $url failed (network error)"
        fi
        return 1
    fi
    if ! curl -fsSL -o "$DOWNLOAD_DIR/$zip_name.sha256" "$url.sha256"; then
        PREBUILT_REASON="checksum $url.sha256 could not be downloaded"
        return 1
    fi
    if ! verify_sha256 "$DOWNLOAD_DIR/$zip_name" "$DOWNLOAD_DIR/$zip_name.sha256"; then
        PREBUILT_REASON="$zip_name does not match its published SHA-256"
        return 1
    fi
    if ! ditto -x -k "$DOWNLOAD_DIR/$zip_name" "$DOWNLOAD_DIR/unpacked" >/dev/null 2>&1; then
        PREBUILT_REASON="could not unpack $zip_name"
        return 1
    fi
    app="$DOWNLOAD_DIR/unpacked/Local-STT.app"
    if [[ ! -f "$app/Contents/MacOS/Local-STT" || ! -x "$app/Contents/MacOS/Local-STT" ]]; then
        PREBUILT_REASON="$zip_name lacks an executable Local-STT.app/Contents/MacOS/Local-STT"
        return 1
    fi
    plist="$app/Contents/Info.plist"
    bundle_id="$(plist_value CFBundleIdentifier "$plist")"
    bundle_version="$(plist_value CFBundleShortVersionString "$plist")"
    if [[ "$bundle_id" != "$BUNDLE_ID" ]]; then
        PREBUILT_REASON="bundle identifier is '$bundle_id', expected '$BUNDLE_ID'"
        return 1
    fi
    if [[ "$bundle_version" != "$VERSION" ]]; then
        PREBUILT_REASON="bundle version is '$bundle_version', expected '$VERSION'"
        return 1
    fi
    APP_SRC="$app"
}

if [[ "$FROM_SOURCE" == "0" ]]; then
    if fetch_prebuilt_app; then
        echo "Using prebuilt app v${VERSION}."
    else
        echo "Prebuilt app not used: $PREBUILT_REASON. Building from source instead."
        require_swift
    fi
fi

if [[ -z "$APP_SRC" ]]; then
    echo "Building Local-STT.app..."
    ( cd "$REPO_DIR" && bash scripts/build-app.sh )

    APP_SRC="$REPO_DIR/dist/Local-STT.app"
    if [[ ! -d "$APP_SRC" ]]; then
        echo "ERROR: build did not produce $APP_SRC" >&2
        exit 1
    fi
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
