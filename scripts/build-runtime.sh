#!/bin/bash
# Build the standalone Python runtime that install.sh unpacks to
# ~/Library/Application Support/Local-STT/venv (#63), so installing needs no
# git, python3 or uv.
#
#   bash scripts/build-runtime.sh        (macOS arm64 only; CI: release.yml)
#
# 1. Download the pinned python-build-standalone CPython and refuse it unless
#    its SHA-256 matches scripts/runtime/python-build-standalone.env.
# 2. Install the hash-locked dependencies (scripts/runtime/requirements.txt)
#    as macOS 13 arm64 wheels, then the local-stt wheel built from this
#    checkout.
# 3. Make console scripts relocatable, move the runtime to another directory
#    and check that it still imports everything.
# 4. Write dist/Local-STT-runtime-v<version>-macos-arm64.tar.gz and its
#    .sha256 (same format as the app zip's).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RUNTIME_DIR="$SCRIPT_DIR/runtime"
PIN_FILE="$RUNTIME_DIR/python-build-standalone.env"
DIST_DIR="$PROJECT_DIR/dist"
STAGE_DIR="$DIST_DIR/runtime"
PBS_BASE_URL="https://github.com/astral-sh/python-build-standalone/releases/download"
# Oldest macOS the menu bar app supports (Package.swift: .macOS(.v13)).
MACOS_MIN="13.0"
# GitHub refuses release assets of 2 GiB or more.
MAX_ASSET_BYTES=2147483647

die() {
    echo "ERROR: $*" >&2
    exit 1
}

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
    die "the runtime is built on macOS arm64 only (this is $(uname -s) $(uname -m))"
fi

# Plain KEY=VALUE parsing: the pin file is data, never sourced.
read_pin() {
    sed -n "s/^$1=\(.*\)$/\1/p" "$PIN_FILE" | head -1
}
[[ -f "$PIN_FILE" ]] || die "missing $PIN_FILE"
PBS_RELEASE="$(read_pin PBS_RELEASE)"
PYTHON_VERSION="$(read_pin PYTHON_VERSION)"
PBS_ASSET="$(read_pin PBS_ASSET)"
PBS_SHA256="$(read_pin PBS_SHA256)"
[[ "$PBS_RELEASE" =~ ^[0-9]{8}$ ]] || die "PBS_RELEASE '$PBS_RELEASE' is not a release date"
[[ "$PYTHON_VERSION" =~ ^3\.[0-9]+\.[0-9]+$ ]] || die "PYTHON_VERSION '$PYTHON_VERSION' is not X.Y.Z"
[[ "$PBS_SHA256" =~ ^[0-9a-f]{64}$ ]] || die "PBS_SHA256 is not a SHA-256 hex digest"
expected_asset="cpython-${PYTHON_VERSION}+${PBS_RELEASE}-aarch64-apple-darwin-install_only_stripped.tar.gz"
[[ "$PBS_ASSET" == "$expected_asset" ]] || die "PBS_ASSET '$PBS_ASSET' does not match '$expected_asset'"
PY_MINOR="${PYTHON_VERSION%.*}"

VERSION="$(sed -n 's/^version[[:space:]]*=[[:space:]]*"\(.*\)"/\1/p' "$PROJECT_DIR/pyproject.toml" | head -1)"
[[ -n "$VERSION" ]] || die "no version found in pyproject.toml"
ASSET_NAME="Local-STT-runtime-v${VERSION}-macos-arm64.tar.gz"

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/local-stt-runtime.XXXXXX")"
cleanup() {
    rm -rf "$WORK_DIR"
}
trap cleanup EXIT

echo "Building standalone runtime v${VERSION} (CPython ${PYTHON_VERSION}, PBS ${PBS_RELEASE})..."

# 1. Pinned CPython, verified before anything is unpacked or run.
pbs_url="$PBS_BASE_URL/$PBS_RELEASE/${PBS_ASSET//+/%2B}"
pbs_file="$WORK_DIR/$PBS_ASSET"
curl -fsSL --retry 3 -o "$pbs_file" "$pbs_url"
actual_sha="$(shasum -a 256 "$pbs_file")"
actual_sha="${actual_sha%% *}"
if [[ "$actual_sha" != "$PBS_SHA256" ]]; then
    die "$PBS_ASSET has SHA-256 $actual_sha, pinned is $PBS_SHA256; refusing to use it"
fi
echo "Verified $PBS_ASSET"

mkdir "$WORK_DIR/pbs"
tar -xzf "$pbs_file" -C "$WORK_DIR/pbs"
[[ -x "$WORK_DIR/pbs/python/bin/python3" ]] || die "$PBS_ASSET lacks python/bin/python3"

rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"
mv "$WORK_DIR/pbs/python" "$STAGE_DIR/venv"
RUNTIME="$STAGE_DIR/venv"
PY="$RUNTIME/bin/python3"
# The app and install.sh look for venv/bin/python.
if [[ ! -e "$RUNTIME/bin/python" ]]; then
    ln -s python3 "$RUNTIME/bin/python"
fi
reported="$("$PY" -I -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
[[ "$reported" == "$PYTHON_VERSION" ]] || die "runtime reports Python $reported, pinned is $PYTHON_VERSION"
SITE="$RUNTIME/lib/python${PY_MINOR}/site-packages"
[[ -d "$SITE" ]] || die "missing $SITE"

PIP=(-I -m pip --disable-pip-version-check --no-input)

# 2a. local-stt wheel, built in a throwaway venv so hatchling does not ship.
"$PY" -I -m venv "$WORK_DIR/buildenv"
"$WORK_DIR/buildenv/bin/python" "${PIP[@]}" install --require-hashes --only-binary :all: \
    -r "$RUNTIME_DIR/build-requirements.txt"
"$WORK_DIR/buildenv/bin/python" "${PIP[@]}" wheel --no-deps --no-build-isolation --no-index \
    -w "$WORK_DIR/wheels" "$PROJECT_DIR"
wheels=("$WORK_DIR"/wheels/local_stt-"$VERSION"-*.whl)
[[ -f "${wheels[0]}" ]] || die "building the local-stt $VERSION wheel failed"

# 2b. Dependencies as macOS 13 arm64 wheels: pip on the runner would otherwise
# pick wheels for the runner's newer macOS (mlx ships one per macOS release).
mac_platform="macosx_${MACOS_MIN/./_}_arm64"
"$PY" "${PIP[@]}" install --require-hashes --only-binary :all: \
    --platform "$mac_platform" --implementation cp \
    --python-version "$PY_MINOR" --abi "cp${PY_MINOR/./}" \
    --target "$SITE" -r "$RUNTIME_DIR/requirements.txt"
# --target puts console scripts here with the runner's interpreter path; the
# runtime only needs `python -m claude_stt.cli`.
rm -rf "${SITE:?}/bin"
"$PY" "${PIP[@]}" install --no-deps --no-index "${wheels[0]}"
"$PY" "${PIP[@]}" check
"$PY" -I "$SCRIPT_DIR/runtime_tool.py" check-macos-tags "$SITE" --max "$MACOS_MIN"

# 3. Relocatable console scripts, then prove the runtime works elsewhere.
"$PY" -I "$SCRIPT_DIR/runtime_tool.py" relocate-scripts "$RUNTIME/bin"
moved_parent="$WORK_DIR/relocation check with spaces"
mkdir -p "$moved_parent"
mv "$RUNTIME" "$moved_parent/venv"
smoke_ok=1
"$moved_parent/venv/bin/python" -I -c '
import claude_stt, claude_stt.cli, mlx.core, mlx_whisper, numpy, sounddevice
import AppKit, Quartz, pynput, objc
print("local-stt", claude_stt.__version__)
' || smoke_ok=0
reported="$("$moved_parent/venv/bin/python" -I -c 'import claude_stt; print(claude_stt.__version__)')" \
    || smoke_ok=0
"$moved_parent/venv/bin/local-stt" --help >/dev/null || smoke_ok=0
mv "$moved_parent/venv" "$RUNTIME"
[[ "$smoke_ok" == "1" ]] || die "the relocated runtime failed its import check"
[[ "$reported" == "$VERSION" ]] || die "runtime reports local-stt '$reported', expected '$VERSION'"

# 4. Package. install.sh expects a single top-level venv/ directory.
find "$RUNTIME" -name '.DS_Store' -delete
ASSET_PATH="$DIST_DIR/$ASSET_NAME"
rm -f "$ASSET_PATH" "$ASSET_PATH.sha256"
tar -C "$STAGE_DIR" -czf "$ASSET_PATH" venv
size="$(wc -c < "$ASSET_PATH" | tr -d ' ')"
if (( size > MAX_ASSET_BYTES )); then
    die "$ASSET_NAME is $size bytes, above the GitHub release asset limit"
fi
( cd "$DIST_DIR" && shasum -a 256 "$ASSET_NAME" > "$ASSET_NAME.sha256" )

echo ""
echo "Built: $ASSET_PATH ($((size / 1024 / 1024)) MiB)"
echo "Checksum: $ASSET_PATH.sha256"
