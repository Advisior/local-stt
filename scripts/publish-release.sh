#!/bin/bash
# Publish a release only once all its assets are attached (#63).
#
#   scripts/publish-release.sh TAG DIST_DIR [CHANGELOG]   (CI: release.yml)
#
# install.sh installs from releases/latest, which never points at a draft.
# Re-runs are idempotent, and a published release is never turned back into a
# draft:
#   - no release for TAG yet: create a draft (notes: this version's CHANGELOG
#     section), upload all assets, check them, then publish. On any failure it
#     stays a draft.
#   - a draft exists: keep its notes, upload (replacing earlier attempts),
#     check, publish.
#   - a published release with all four assets: verify and leave it unchanged.
#   - a published release lacking assets (created in the web UI before the
#     workflow ran): upload only the missing ones, never replacing an attached
#     asset, and stay published. Builds are not reproducible, so when only one
#     half of an archive/checksum pair is attached, the attached half is
#     downloaded and the other half is only added if they match; otherwise
#     (or if that check cannot be done) nothing is uploaded. Every pair is
#     checked before the first upload; a failure leaves the release as it was.
# To replace assets of a published release, make it a draft by hand and re-run
# the workflow.
#
# Needs: gh (authenticated, contents: write), GITHUB_REPOSITORY, shasum.
set -euo pipefail

die() {
    echo "ERROR: $*" >&2
    exit 1
}

[[ $# -ge 2 ]] || die "usage: $0 TAG DIST_DIR [CHANGELOG]"
TAG="$1"
DIST_DIR="$2"
CHANGELOG="${3:-CHANGELOG.md}"
REPO="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY must be set}"

# Same tag shape install.sh accepts; also keeps TAG safe inside the jq filter.
[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+[0-9A-Za-z.+-]*$ ]] || die "'$TAG' is not a release tag"
VERSION="${TAG#v}"
RUNTIME="Local-STT-runtime-v${VERSION}-macos-arm64.tar.gz"
APP="Local-STT-v${VERSION}.zip"
ASSETS=("$RUNTIME" "$RUNTIME.sha256" "$APP" "$APP.sha256")

# 1. Everything present and matching its checksum before touching the release.
for asset in "${ASSETS[@]}"; do
    [[ -f "$DIST_DIR/$asset" ]] || die "$DIST_DIR/$asset is missing"
done
( cd "$DIST_DIR" && shasum -a 256 -c "$RUNTIME.sha256" "$APP.sha256" ) \
    || die "an asset does not match its checksum"

# Prints "<id> <draft>" for the release of TAG, drafts included (the
# releases/tags endpoint does not return drafts).
find_release() {
    gh api --paginate "repos/$REPO/releases?per_page=100" \
        --jq ".[] | select(.tag_name == \"$TAG\") | \"\(.id) \(.draft)\"" | head -1
}

release_notes() {
    local section
    section="$(awk -v head="## [$VERSION]" '
        index($0, head) == 1 { found = 1; next }
        found && /^## \[/ { exit }
        found { print }
    ' "$CHANGELOG" 2>/dev/null || true)"
    if [[ -z "${section//[[:space:]]/}" ]]; then
        section="See [CHANGELOG.md](https://github.com/$REPO/blob/main/CHANGELOG.md)."
    fi
    # shellcheck disable=SC2016  # the backticks are Markdown, not shell
    printf '%s\n\n## Install or update\n\n```bash\ncurl -fsSL https://raw.githubusercontent.com/%s/main/install.sh | bash\n```\n' \
        "$section" "$REPO"
}

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/publish-release.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT

# Prints the ASSETS that the release $1 does not have fully uploaded, one per
# line; nothing when it is complete. Returns non-zero when the lookup fails.
missing_assets() {
    local attached asset
    attached="$(gh api "repos/$REPO/releases/$1" \
        --jq '.assets[] | select(.state == "uploaded") | .name')" || return 1
    for asset in "${ASSETS[@]}"; do
        if ! grep -qxF "$asset" <<< "$attached"; then
            echo "$asset"
        fi
    done
}

# Sets the array LACKING to missing_assets of release $1. The output is
# captured in a variable first so a failed lookup aborts instead of reading
# as "nothing missing" (no process substitution, no mapfile: bash 3.2 on
# macOS runs the tests too).
read_lacking() {
    local out line
    out="$(missing_assets "$1")" || die "could not read the assets of release $TAG"
    LACKING=()
    while IFS= read -r line; do
        if [[ -n "$line" ]]; then
            LACKING+=("$line")
        fi
    done <<< "$out"
}

is_lacking() {
    local item
    for item in "${LACKING[@]}"; do
        [[ "$item" == "$1" ]] && return 0
    done
    return 1
}

# Prints the digest from a `shasum -a 256` file, lowercased; fails if it is
# not a SHA-256 hex digest.
digest_of() {
    local digest=""
    read -r digest _ < "$1" || true
    digest="$(printf '%s' "$digest" | tr 'A-F' 'a-f')"
    [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || return 1
    echo "$digest"
}

# Downloads the attached asset $1 of TAG into WORK_DIR/remote and prints its
# path; dies (fail closed) when that is not possible.
fetch_remote() {
    local dir="$WORK_DIR/remote"
    mkdir -p "$dir"
    if ! gh release download "$TAG" --repo "$REPO" --pattern "$1" --dir "$dir" >/dev/null \
        || [[ ! -f "$dir/$1" ]]; then
        die "could not download the attached $1 to check it; $TAG left unchanged"
    fi
    echo "$dir/$1"
}

# Prints the files to upload for the archive $1 and its checksum, or dies
# when only one of them is attached and the attached one does not belong to
# this build: builds are not reproducible, and install.sh rejects an archive
# whose checksum does not match.
plan_pair() {
    local archive="$1" checksum="$1.sha256" local_digest remote remote_digest
    local_digest="$(digest_of "$DIST_DIR/$checksum")" || die "malformed $DIST_DIR/$checksum"
    if is_lacking "$archive" && is_lacking "$checksum"; then
        echo "$archive"
        echo "$checksum"
    elif is_lacking "$checksum"; then
        # errexit does not reach into $(...) on bash 3.2: exit explicitly.
        remote="$(fetch_remote "$archive")" || exit 1
        remote_digest="$(shasum -a 256 "$remote")" || die "could not hash the attached $archive"
        remote_digest="${remote_digest%% *}"
        [[ "$remote_digest" == "$local_digest" ]] \
            || die "the attached $archive does not match this build's $checksum; $TAG left unchanged"
        echo "$checksum"
    elif is_lacking "$archive"; then
        remote="$(fetch_remote "$checksum")" || exit 1
        remote_digest="$(digest_of "$remote")" \
            || die "the attached $checksum is malformed; $TAG left unchanged"
        [[ "$remote_digest" == "$local_digest" ]] \
            || die "the attached $checksum does not match this build's $archive; $TAG left unchanged"
        echo "$archive"
    fi
}

# 2. Find or create the release for TAG. A failing lookup aborts here
# (set -e, pipefail) instead of looking like "no release yet".
found="$(find_release)"
release_id="" is_draft=""
read -r release_id is_draft <<< "$found" || true
if [[ -z "$release_id" ]]; then
    notes_file="$WORK_DIR/release-notes.md"
    release_notes > "$notes_file"
    echo "Creating draft release $TAG..."
    gh release create "$TAG" --repo "$REPO" --draft --verify-tag --title "$TAG" \
        --notes-file "$notes_file"
    found="$(find_release)"
    read -r release_id is_draft <<< "$found" || true
    [[ -n "$release_id" && "$is_draft" == "true" ]] || die "draft release $TAG not found after creating it"
fi
[[ "$release_id" =~ ^[0-9]+$ ]] || die "unexpected release id '$release_id'"

# 3a. Published: never downgrade, never replace; only add what is missing,
# and only what provably belongs with what is attached. Every pair is
# checked before anything is uploaded.
if [[ "$is_draft" != "true" ]]; then
    read_lacking "$release_id"
    if [[ ${#LACKING[@]} -eq 0 ]]; then
        echo "Release $TAG is already published with all assets; leaving it unchanged."
        exit 0
    fi
    echo "Release $TAG is published but lacks ${LACKING[*]}; adding them (it stays published)."
    # Runtime pair before the app pair. Each plan is captured in a variable so
    # a refusal (die in the subshell) stops the script before any upload.
    runtime_plan="$(plan_pair "$RUNTIME")" || exit 1
    app_plan="$(plan_pair "$APP")" || exit 1
    while IFS= read -r asset; do
        if [[ -n "$asset" ]]; then
            gh release upload "$TAG" --repo "$REPO" "$DIST_DIR/$asset"
        fi
    done <<< "$runtime_plan
$app_plan"
    read_lacking "$release_id"
    [[ ${#LACKING[@]} -eq 0 ]] || die "$TAG still lacks ${LACKING[*]}"
    echo "Completed $TAG with ${ASSETS[*]}"
    exit 0
fi

# 3b. Draft: upload runtime first, then the app zip (replacing partial
# uploads of an earlier attempt), and publish only when all are attached.
gh release upload "$TAG" --repo "$REPO" --clobber "$DIST_DIR/$RUNTIME" "$DIST_DIR/$RUNTIME.sha256"
gh release upload "$TAG" --repo "$REPO" --clobber "$DIST_DIR/$APP" "$DIST_DIR/$APP.sha256"
read_lacking "$release_id"
[[ ${#LACKING[@]} -eq 0 ]] || die "${LACKING[*]} not attached; $TAG stays a draft"
# legacy: "latest" follows date and semver, so re-running an old tag does not
# make it the release install.sh picks.
gh api -X PATCH "repos/$REPO/releases/$release_id" -F draft=false -f make_latest=legacy >/dev/null
echo "Published $TAG with ${ASSETS[*]}"
