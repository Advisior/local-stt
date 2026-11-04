"""Tests for scripts/publish-release.sh with `gh` stubbed (#63).

The release stays a draft until the runtime, the app zip and both checksums
are attached; only then is it published. Nothing here talks to GitHub.
"""

import hashlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "publish-release.sh"
_VERSION = "1.2.3"
_TAG = f"v{_VERSION}"
_REPO = "Advisior/local-stt"
_RUNTIME = f"Local-STT-runtime-{_TAG}-macos-arm64.tar.gz"
_APP = f"Local-STT-{_TAG}.zip"
_ALL = [_RUNTIME, f"{_RUNTIME}.sha256", _APP, f"{_APP}.sha256"]

_REAL_TOOLS = ("awk", "bash", "cat", "dirname", "grep", "head", "mktemp", "rm", "sed", "shasum",
               "tr")

# State lives in files: release.state is none, draft or published; assets.txt
# lists attached asset names.
_GH_STUB = r"""#!/bin/bash
echo "gh $*" >> "$STUB_LOG"
state="$(cat "$GH_DIR/release.state")"
case "$1 $2" in
    "api --paginate")
        [[ -z "${FAKE_LIST_FAIL:-}" ]] || exit 1
        [[ "$state" == "none" ]] || echo "42 $([[ "$state" == draft ]] && echo true || echo false)"
        ;;
    "release create")
        notes=""
        while [[ $# -gt 0 ]]; do
            [[ "$1" == "--notes-file" ]] && notes="$2"
            shift
        done
        cp "$notes" "$GH_DIR/notes.md"
        echo draft > "$GH_DIR/release.state"
        ;;
    "release upload")
        [[ -z "${FAKE_UPLOAD_FAIL:-}" ]] || exit 1
        for arg in "$@"; do
            if [[ -f "$arg" ]]; then
                name="${arg##*/}"
                [[ "$name" == "${FAKE_DROP_ASSET:-}" ]] || echo "$name" >> "$GH_DIR/assets.txt"
            fi
        done
        ;;
    "api -X")
        if [[ "$*" == *"draft=true"* ]]; then
            echo draft > "$GH_DIR/release.state"
        elif [[ "$*" == *"draft=false"* ]]; then
            echo published > "$GH_DIR/release.state"
        fi
        ;;
    "api repos/"*)
        cat "$GH_DIR/assets.txt" 2>/dev/null || true
        ;;
    *)
        echo "unexpected gh call: $*" >&2
        exit 2
        ;;
esac
"""

_CHANGELOG = f"""# Changelog

## [Unreleased]

## [{_VERSION}] - 2026-11-03

### Added
- The new thing (#63)

## [1.2.2] - 2026-10-31

### Fixed
- An older thing
"""


@unittest.skipIf(sys.platform == "win32", "publish-release.sh is a bash script for CI")
class PublishReleaseScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for tool in _REAL_TOOLS:
            real = shutil.which(tool)
            self.assertIsNotNone(real, f"missing real tool {tool}")
            (self.bin / tool).symlink_to(real)
        # The stub copies notes with cp; the script itself does not need it.
        (self.bin / "cp").symlink_to(shutil.which("cp"))
        gh = self.bin / "gh"
        gh.write_text(_GH_STUB)
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR)

        self.gh_dir = self.tmp / "gh"
        self.gh_dir.mkdir()
        self.set_release("none")
        self.log = self.tmp / "stub.log"
        self.log.touch()

        self.dist = self.tmp / "dist"
        self.dist.mkdir()
        for name, data in ((_RUNTIME, b"runtime"), (_APP, b"app")):
            (self.dist / name).write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            (self.dist / f"{name}.sha256").write_text(f"{digest}  {name}\n")
        self.changelog = self.tmp / "CHANGELOG.md"
        self.changelog.write_text(_CHANGELOG)

    def set_release(self, state):
        (self.gh_dir / "release.state").write_text(state + "\n")

    def release_state(self):
        return (self.gh_dir / "release.state").read_text().strip()

    def run_publish(self, tag=_TAG, **env):
        return subprocess.run(
            ["bash", str(_SCRIPT), tag, str(self.dist), str(self.changelog)],
            cwd=self.tmp,
            env={"PATH": str(self.bin), "HOME": str(self.tmp), "TMPDIR": str(self.tmp),
                 "GITHUB_REPOSITORY": _REPO, "STUB_LOG": str(self.log),
                 "GH_DIR": str(self.gh_dir), **env},
            capture_output=True,
            text=True,
            timeout=60,
        )

    def gh_calls(self):
        return self.log.read_text().splitlines()

    def index_of(self, needle):
        calls = self.gh_calls()
        for i, line in enumerate(calls):
            if needle in line:
                return i
        self.fail(f"{needle!r} not in {calls}")

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_published_after_all_uploads(self):
        publish = self.index_of("draft=false")
        self.assertEqual(publish, len(self.gh_calls()) - 1, "publishing is the last call")
        self.assertLess(self.index_of(f"{self.dist}/{_RUNTIME} "), self.index_of(_APP))
        self.assertLess(self.index_of(_APP), publish)
        self.assertIn("make_latest=legacy", self.gh_calls()[publish])
        self.assertEqual(self.release_state(), "published")
        attached = (self.gh_dir / "assets.txt").read_text().split()
        self.assertEqual(sorted(attached), sorted(_ALL))

    # -- happy paths -----------------------------------------------------

    def test_given_no_release_then_creates_draft_uploads_all_then_publishes(self):
        result = self.run_publish()
        self.assert_ok(result)
        create = self.gh_calls()[self.index_of("release create")]
        for flag in (f"release create {_TAG}", f"--repo {_REPO}", "--draft", "--verify-tag",
                     f"--title {_TAG}"):
            self.assertIn(flag, create)
        self.assertLess(self.index_of("release create"), self.index_of("release upload"))
        self.assert_published_after_all_uploads()

    def test_given_no_release_then_notes_are_this_versions_changelog_section(self):
        self.assert_ok(self.run_publish())
        notes = (self.gh_dir / "notes.md").read_text()
        self.assertIn("### Added\n- The new thing (#63)", notes)
        self.assertNotIn("An older thing", notes)
        self.assertNotIn("Unreleased", notes)
        self.assertIn("install.sh", notes)

    def test_given_draft_release_then_keeps_it_and_publishes_after_uploads(self):
        self.set_release("draft")
        result = self.run_publish()
        self.assert_ok(result)
        self.assertFalse(any("release create" in c for c in self.gh_calls()))
        self.assertFalse(any("draft=true" in c for c in self.gh_calls()))
        self.assert_published_after_all_uploads()

    def assert_never_downgraded(self):
        self.assertEqual(self.release_state(), "published")
        self.assertFalse(any("draft=true" in c or "-X PATCH" in c for c in self.gh_calls()),
                         self.gh_calls())
        self.assertFalse(any("--clobber" in c for c in self.gh_calls()), self.gh_calls())

    def test_given_published_release_without_assets_then_adds_them_without_drafting(self):
        self.set_release("published")
        result = self.run_publish()
        self.assert_ok(result)
        self.assert_never_downgraded()
        self.assertLess(self.index_of(f"{self.dist}/{_RUNTIME}"), self.index_of(_APP))
        attached = (self.gh_dir / "assets.txt").read_text().split()
        self.assertEqual(sorted(attached), sorted(_ALL))

    def test_given_complete_published_release_when_rerun_then_left_untouched(self):
        self.set_release("published")
        (self.gh_dir / "assets.txt").write_text("\n".join(_ALL) + "\n")
        result = self.run_publish()
        self.assert_ok(result)
        self.assertIn("already published with all assets", result.stdout)
        self.assert_never_downgraded()
        self.assertFalse(any("release upload" in c for c in self.gh_calls()), self.gh_calls())

    def test_given_published_release_missing_one_asset_then_uploads_only_that_one(self):
        self.set_release("published")
        (self.gh_dir / "assets.txt").write_text("\n".join(_ALL[:3]) + "\n")
        result = self.run_publish()
        self.assert_ok(result)
        self.assertIn(f"lacks {_APP}.sha256", result.stdout)
        self.assert_never_downgraded()
        uploads = [c for c in self.gh_calls() if "release upload" in c]
        self.assertEqual(len(uploads), 1, uploads)
        self.assertTrue(uploads[0].endswith(f"{self.dist}/{_APP}.sha256"), uploads)

    # -- refusals: the release is never published incomplete --------------

    def test_given_checksum_mismatch_then_no_github_call(self):
        (self.dist / _APP).write_bytes(b"tampered")
        result = self.run_publish()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.gh_calls(), [])

    def test_given_missing_asset_then_no_github_call(self):
        for name in _ALL:
            with self.subTest(name=name):
                self.log.write_text("")
                saved = (self.dist / name).read_bytes()
                (self.dist / name).unlink()
                result = self.run_publish()
                (self.dist / name).write_bytes(saved)
                self.assertEqual(result.returncode, 1)
                self.assertIn(name, result.stderr)
                self.assertEqual(self.gh_calls(), [])

    def test_given_bad_tag_then_refuses(self):
        for tag in ("1.2.3", "v1.2", "v1.2.3;rm", "v1.2.4"):
            with self.subTest(tag=tag):
                result = self.run_publish(tag=tag)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(self.gh_calls(), [])

    def test_given_upload_failure_then_release_stays_draft(self):
        result = self.run_publish(FAKE_UPLOAD_FAIL="1")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.release_state(), "draft")
        self.assertFalse(any("draft=false" in c for c in self.gh_calls()))

    def test_given_upload_failure_on_published_release_then_it_stays_published(self):
        self.set_release("published")
        (self.gh_dir / "assets.txt").write_text(f"{_APP}\n{_APP}.sha256\n")
        result = self.run_publish(FAKE_UPLOAD_FAIL="1")
        self.assertEqual(result.returncode, 1)
        self.assert_never_downgraded()

    def test_given_asset_missing_after_upload_then_release_stays_draft(self):
        result = self.run_publish(FAKE_DROP_ASSET=f"{_RUNTIME}.sha256")
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"{_RUNTIME}.sha256 not attached; {_TAG} stays a draft", result.stderr)
        self.assertEqual(self.release_state(), "draft")
        self.assertFalse(any("draft=false" in c for c in self.gh_calls()))

    def test_given_release_lookup_fails_then_aborts_without_creating(self):
        result = self.run_publish(FAKE_LIST_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("release create" in c for c in self.gh_calls()))
        self.assertFalse(any("upload" in c for c in self.gh_calls()))

    def test_given_changelog_without_section_then_notes_point_to_changelog(self):
        self.changelog.write_text("# Changelog\n")
        self.assert_ok(self.run_publish())
        self.assertIn("CHANGELOG.md", (self.gh_dir / "notes.md").read_text())


if __name__ == "__main__":
    unittest.main()
