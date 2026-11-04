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
#     asset, and stay published. A failure leaves it as it was.
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

# Prints the ASSETS that the release $1 does not have fully uploaded, one per
# line; nothing when it is complete.
missing_assets() {
    local attached asset
    attached="$(gh api "repos/$REPO/releases/$1" \
        --jq '.assets[] | select(.state == "uploaded") | .name')"
    for asset in "${ASSETS[@]}"; do
        grep -qxF "$asset" <<< "$attached" || echo "$asset"
    done
}

# Sets the array LACKING to missing_assets of release $1 (bash 3.2 has no
# mapfile, and the tests run on macOS too).
read_lacking() {
    local line
    LACKING=()
    while IFS= read -r line; do
        [[ -n "$line" ]] && LACKING+=("$line")
    done < <(missing_assets "$1")
}

# 2. Find or create the release for TAG. A failing lookup aborts here
# (set -e, pipefail) instead of looking like "no release yet".
found="$(find_release)"
release_id="" is_draft=""
read -r release_id is_draft <<< "$found" || true
if [[ -z "$release_id" ]]; then
    notes_file="$(mktemp "${TMPDIR:-/tmp}/release-notes.XXXXXX")"
    trap 'rm -f "$notes_file"' EXIT
    release_notes > "$notes_file"
    echo "Creating draft release $TAG..."
    gh release create "$TAG" --repo "$REPO" --draft --verify-tag --title "$TAG" \
        --notes-file "$notes_file"
    found="$(find_release)"
    read -r release_id is_draft <<< "$found" || true
    [[ -n "$release_id" && "$is_draft" == "true" ]] || die "draft release $TAG not found after creating it"
fi
[[ "$release_id" =~ ^[0-9]+$ ]] || die "unexpected release id '$release_id'"

# 3a. Published: never downgrade, never replace; only add what is missing.
if [[ "$is_draft" != "true" ]]; then
    read_lacking "$release_id"
    if [[ ${#LACKING[@]} -eq 0 ]]; then
        echo "Release $TAG is already published with all assets; leaving it unchanged."
        exit 0
    fi
    echo "Release $TAG is published but lacks ${LACKING[*]}; adding them (it stays published)."
    # ASSETS order: runtime and its checksum before the app zip.
    for asset in "${LACKING[@]}"; do
        gh release upload "$TAG" --repo "$REPO" "$DIST_DIR/$asset"
    done
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
