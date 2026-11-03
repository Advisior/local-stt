#!/bin/bash
# Publish a release only once all its assets are attached (#63).
#
#   scripts/publish-release.sh TAG DIST_DIR [CHANGELOG]   (CI: release.yml)
#
# install.sh installs from releases/latest, which never points at a draft. So
# the release is kept a draft while assets are uploaded and published last:
#   - no release for TAG yet: create a draft (notes: this version's CHANGELOG
#     section)
#   - a draft exists: keep its notes and use it
#   - a published release exists (created in the web UI): turn it back into a
#     draft first; releases/latest then points at the previous release
# Then upload runtime + checksum, app zip + checksum, check that all four are
# attached, and publish. On any failure the release stays a draft.
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

# 2. A draft release for TAG.
# A failing lookup aborts here (set -e, pipefail) instead of looking like
# "no release yet".
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
elif [[ "$is_draft" != "true" ]]; then
    echo "Release $TAG is public without its assets; turning it back into a draft until all assets are attached."
    gh api -X PATCH "repos/$REPO/releases/$release_id" -F draft=true >/dev/null
fi
[[ "$release_id" =~ ^[0-9]+$ ]] || die "unexpected release id '$release_id'"

# 3. Upload: runtime first, then the app zip.
gh release upload "$TAG" --repo "$REPO" --clobber "$DIST_DIR/$RUNTIME" "$DIST_DIR/$RUNTIME.sha256"
gh release upload "$TAG" --repo "$REPO" --clobber "$DIST_DIR/$APP" "$DIST_DIR/$APP.sha256"

# 4. Publish only when every asset is attached.
attached="$(gh api "repos/$REPO/releases/$release_id" --jq '.assets[].name')"
for asset in "${ASSETS[@]}"; do
    grep -qxF "$asset" <<< "$attached" || die "$asset is not attached; $TAG stays a draft"
done
# legacy: "latest" follows date and semver, so re-running an old tag does not
# make it the release install.sh picks.
gh api -X PATCH "repos/$REPO/releases/$release_id" -F draft=false -f make_latest=legacy >/dev/null
echo "Published $TAG with ${ASSETS[*]}"
