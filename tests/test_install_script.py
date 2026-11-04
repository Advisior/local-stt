"""Tests for install.sh with every external tool stubbed on PATH.

Nothing here touches the network, /Applications or Login Items: curl, git,
ditto, uv, swift, osascript and xattr are stubs, and cp/rm refuse any path
under /Applications and only log it.
"""

import hashlib
import io
import plistlib
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import unittest
from pathlib import Path

_INSTALL_SH = Path(__file__).resolve().parents[1] / "install.sh"
_VERSION = "1.2.3"
_TAG = f"v{_VERSION}"
_ZIP_URL = (
    f"https://github.com/Advisior/local-stt/releases/download/{_TAG}/Local-STT-{_TAG}.zip"
)

# Real tools the installer needs besides the stubbed ones. swift, python3 and
# brew are deliberately not linked, so a test controls whether they exist.
_REAL_TOOLS = (
    "bash", "cat", "dirname", "grep", "gzip", "head", "mkdir", "mktemp", "mv", "sed", "shasum",
    "tail", "tar", "tr",
)
_ZIP_BYTES = b"zip\n"  # what the curl stub writes for the zip

_STUBS = {
    "uname": """
        case "$1" in
            -s) echo Darwin ;;
            -m) echo arm64 ;;
        esac
    """,
    "curl": """
        echo "curl $*" >> "$STUB_LOG"
        if [[ "$1" == "-sI" ]]; then
            echo "HTTP/2 302"
            if [[ -n "${FAKE_LATEST_LOCATION:-}" ]]; then
                printf 'location: %s\\r\\n' "$FAKE_LATEST_LOCATION"
            fi
            exit 0
        fi
        out=""
        url=""
        while [[ $# -gt 0 ]]; do
            if [[ "$1" == "-o" ]]; then out="$2"; shift; else url="$1"; fi
            shift
        done
        if [[ "$url" == *Local-STT-runtime-*.tar.gz.sha256 ]]; then
            [[ "${FAKE_RUNTIME_SHA_DOWNLOAD:-ok}" == "ok" ]] || exit 22
            printf '%s  runtime.tar.gz\n' "$FAKE_RUNTIME_SHA256" > "$out"
            exit 0
        fi
        if [[ "$url" == *Local-STT-runtime-*.tar.gz ]]; then
            # Default 404: releases before #63 have no runtime asset.
            case "${FAKE_RUNTIME:-404}" in
                ok) cp "$FAKE_RUNTIME_TARBALL" "$out"; printf 200 ;;
                404) printf 404; exit 22 ;;
                network) printf 000; exit 6 ;;
            esac
            exit 0
        fi
        if [[ "$url" == *.sha256 ]]; then
            [[ "${FAKE_SHA_DOWNLOAD:-ok}" == "ok" ]] || exit 22
            printf '%s  Local-STT.zip\n' "$FAKE_SHA256" > "$out"
            exit 0
        fi
        case "${FAKE_DOWNLOAD:-ok}" in
            ok) echo zip > "$out"; printf 200 ;;
            404) printf 404; exit 22 ;;
            network) printf 000; exit 6 ;;
        esac
    """,
    "ditto": """
        echo "ditto $*" >> "$STUB_LOG"
        [[ "${FAKE_UNPACK:-ok}" == "ok" ]] || exit 1
        mkdir -p "$4"
        /bin/cp -R "$FAKE_APP_SRC" "$4/"
    """,
    "git": """
        echo "git $*" >> "$STUB_LOG"
        if [[ "$1" == "clone" ]]; then
            dest="${@: -1}"
            mkdir -p "$dest/scripts"
            printf 'name = "local-stt"\\nversion = "%s"\\n' "$FAKE_VERSION" > "$dest/pyproject.toml"
            /bin/cp "$FAKE_BUILD_SCRIPT" "$dest/scripts/build-app.sh"
        fi
    """,
    "uv": """
        echo "uv $*" >> "$STUB_LOG"
        if [[ "$1" == "venv" ]]; then mkdir -p "$2/bin"; fi
    """,
    "swift": 'echo "swift $*" >> "$STUB_LOG"',
    "xattr": 'echo "xattr $*" >> "$STUB_LOG"',
    "osascript": 'echo "osascript $*" >> "$STUB_LOG"; exit 1',
    "cp": """
        if [[ "${@: -1}" == /Applications* ]]; then
            echo "INSTALL $*" >> "$STUB_LOG"
            exit 0
        fi
        exec /bin/cp "$@"
    """,
    "rm": """
        for arg in "$@"; do
            if [[ "$arg" == /Applications* ]]; then
                echo "REMOVE $*" >> "$STUB_LOG"
                exit 0
            fi
        done
        exec /bin/rm "$@"
    """,
}

_BUILD_SCRIPT = """#!/bin/bash
echo "BUILD $(pwd)" >> "$STUB_LOG"
mkdir -p dist/Local-STT.app/Contents/MacOS
"""

# The python of the fake standalone runtime: answers the version check.
_RUNTIME_PYTHON = """#!/bin/bash
echo "runtime-python $*" >> "$STUB_LOG"
[[ -z "${FAKE_RUNTIME_BROKEN:-}" ]] || exit 1
echo "${FAKE_RUNTIME_REPORTS:-$FAKE_VERSION}"
"""
_RUNTIME_URL = (
    f"https://github.com/Advisior/local-stt/releases/download/{_TAG}"
    f"/Local-STT-runtime-{_TAG}-macos-arm64.tar.gz"
)


def _make_tarball(path: Path, files: dict) -> None:
    """files maps archive names to (bytes, mode)."""
    with tarfile.open(path, "w:gz") as tar:
        for name, (data, mode) in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = mode
            tar.addfile(info, io.BytesIO(data))


# Stand-in for macOS plutil on Linux CI; only the call install.sh makes.
_PLUTIL_STUB = f"""#!{sys.executable}
import plistlib, sys
key, path = sys.argv[2], sys.argv[-1]
try:
    with open(path, "rb") as fh:
        print(plistlib.load(fh)[key])
except Exception:
    sys.exit(1)
"""


def _write_exec(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@unittest.skipIf(sys.platform == "win32", "install.sh is a bash script for macOS")
class InstallScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.prefix = self.tmp / "prefix"
        self.tmpdir = self.tmp / "tmpdir"
        self.tmpdir.mkdir()
        self.log = self.tmp / "stub.log"
        self.log.touch()

        for tool in _REAL_TOOLS:
            real = shutil.which(tool)
            self.assertIsNotNone(real, f"missing real tool {tool}")
            (self.bin / tool).symlink_to(real)
        for name, body in _STUBS.items():
            _write_exec(self.bin / name, "#!/bin/bash\n" + textwrap.dedent(body))
        if sys.platform == "darwin" and Path("/usr/bin/plutil").exists():
            (self.bin / "plutil").symlink_to("/usr/bin/plutil")
        else:
            _write_exec(self.bin / "plutil", _PLUTIL_STUB)

        self.build_script = self.tmp / "build-app.sh"
        _write_exec(self.build_script, _BUILD_SCRIPT)
        self.app_src = self.tmp / "release" / "Local-STT.app"
        self.make_release_app()

        self.runtime_tarball = self.tmp / "runtime.tar.gz"
        self.make_runtime()

        self.env = {
            "PATH": str(self.bin),
            "HOME": str(self.tmp / "home"),
            "TMPDIR": str(self.tmpdir),
            "STUB_LOG": str(self.log),
            "FAKE_VERSION": _VERSION,
            "FAKE_APP_SRC": str(self.app_src),
            "FAKE_BUILD_SCRIPT": str(self.build_script),
            "FAKE_SHA256": hashlib.sha256(_ZIP_BYTES).hexdigest(),
            "FAKE_LATEST_LOCATION": f"https://github.com/Advisior/local-stt/releases/tag/{_TAG}",
            "FAKE_RUNTIME_TARBALL": str(self.runtime_tarball),
        }
        self.env["FAKE_RUNTIME_SHA256"] = self.runtime_sha()

    # -- helpers ---------------------------------------------------------

    def make_release_app(self, bundle_id="com.local-stt.menubar", version=_VERSION,
                         executable=True, exec_bit=True):
        if self.app_src.exists():
            shutil.rmtree(self.app_src)
        macos = self.app_src / "Contents" / "MacOS"
        macos.mkdir(parents=True)
        if executable:
            binary = macos / "Local-STT"
            binary.write_text("binary")
            if exec_bit:
                binary.chmod(0o755)
        with open(self.app_src / "Contents" / "Info.plist", "wb") as fh:
            plistlib.dump(
                {"CFBundleIdentifier": bundle_id, "CFBundleShortVersionString": version}, fh
            )

    def remove_swift(self):
        (self.bin / "swift").unlink()

    def remove_tools(self, *names):
        for name in names:
            (self.bin / name).unlink()

    def make_runtime(self, files=None):
        if files is None:
            files = {"venv/bin/python": (_RUNTIME_PYTHON.encode(), 0o755),
                     "venv/lib/python3.12/site-packages/claude_stt/__init__.py": (b"", 0o644)}
        _make_tarball(self.runtime_tarball, files)

    def runtime_sha(self):
        return hashlib.sha256(self.runtime_tarball.read_bytes()).hexdigest()

    def run_remote(self, *args, **env):
        """Simulates `curl ... | bash`: the script arrives on stdin."""
        return subprocess.run(
            ["bash", "-s", "--", "--prefix", str(self.prefix), "--login-item", "no", *args],
            input=_INSTALL_SH.read_text(),
            cwd=self.tmp,
            env={**self.env, **env},
            capture_output=True,
            text=True,
            timeout=60,
        )

    def run_local(self, *args):
        """Runs install.sh from a local checkout on disk (development)."""
        repo = self.tmp / "checkout"
        (repo / "scripts").mkdir(parents=True)
        shutil.copy(_INSTALL_SH, repo / "install.sh")
        (repo / "pyproject.toml").write_text(f'name = "local-stt"\nversion = "{_VERSION}"\n')
        shutil.copy(self.build_script, repo / "scripts" / "build-app.sh")
        return subprocess.run(
            ["bash", str(repo / "install.sh"), "--prefix", str(self.prefix),
             "--login-item", "no", *args],
            cwd=self.tmp,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def stub_log(self):
        return self.log.read_text().splitlines()

    def logged(self, prefix):
        return [line for line in self.stub_log() if line.startswith(prefix)]

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_built_from_source(self, result):
        self.assert_ok(result)
        self.assertEqual(len(self.logged("BUILD")), 1, self.stub_log())
        self.assertIn("/dist/Local-STT.app", self.logged("INSTALL")[0])

    def reason_lines(self, result):
        return [line for line in result.stdout.splitlines()
                if line.startswith("Prebuilt app not used:")]

    def leftover_download_dirs(self):
        return list(self.tmpdir.glob("local-stt-install.*"))

    def runtime_reason_lines(self, result):
        return [line for line in result.stdout.splitlines()
                if line.startswith("Standalone runtime not used:")]

    def assert_python_env_from_uv(self, result):
        self.assert_ok(result)
        self.assertTrue(self.logged("uv venv"), self.stub_log())
        self.assertEqual(self.logged("runtime-python"), [])
        self.assertEqual(list(self.prefix.glob(".runtime.*")), [])

    # -- AC-1 ------------------------------------------------------------

    def test_ac1_given_release_zip_when_remote_install_then_installs_prebuilt_without_swift(self):
        self.remove_swift()
        result = self.run_remote()
        self.assert_ok(result)
        self.assertIn("curl -fsSL -o", "\n".join(self.logged("curl")))
        self.assertTrue(any(_ZIP_URL in line for line in self.logged("curl")))
        unpack = self.logged("ditto")
        self.assertEqual(len(unpack), 1)
        self.assertTrue(unpack[0].startswith("ditto -x -k "), unpack)
        self.assertEqual(self.logged("BUILD"), [])
        install = self.logged("INSTALL")
        self.assertEqual(len(install), 1)
        self.assertIn("local-stt-install.", install[0])
        self.assertIn("/unpacked/Local-STT.app /Applications/Local-STT.app", install[0])
        self.assertIn("Using prebuilt app v1.2.3.", result.stdout)

    def test_ac1_given_checkout_version_when_downloading_then_url_uses_pyproject_version(self):
        result = self.run_remote(FAKE_VERSION="2.0.1")
        self.assert_ok(result)
        url = "releases/download/v2.0.1/Local-STT-v2.0.1.zip"
        self.assertTrue(any(url in line for line in self.logged("curl")), self.stub_log())

    # -- AC-2 ------------------------------------------------------------

    def test_ac2_given_missing_release_when_download_404_then_one_reason_line_and_source_build(self):
        result = self.run_remote(FAKE_DOWNLOAD="404")
        self.assert_built_from_source(result)
        reasons = self.reason_lines(result)
        self.assertEqual(len(reasons), 1, result.stdout)
        self.assertIn("HTTP 404", reasons[0])

    def test_ac2_given_network_failure_when_downloading_then_falls_back(self):
        result = self.run_remote(FAKE_DOWNLOAD="network")
        self.assert_built_from_source(result)
        self.assertIn("network error", self.reason_lines(result)[0])

    def test_given_checksum_matches_when_downloading_then_uses_prebuilt(self):
        result = self.run_remote(FAKE_SHA256=hashlib.sha256(_ZIP_BYTES).hexdigest().upper())
        self.assert_ok(result)
        self.assertEqual(self.logged("BUILD"), [])
        self.assertTrue(any(f"{_ZIP_URL}.sha256" in line for line in self.logged("curl")))

    def test_given_checksum_mismatch_when_downloading_then_falls_back(self):
        result = self.run_remote(FAKE_SHA256="0" * 64)
        self.assert_built_from_source(result)
        self.assertIn("does not match its published SHA-256", self.reason_lines(result)[0])
        self.assertEqual(self.logged("ditto"), [])

    def test_given_malformed_checksum_when_downloading_then_falls_back(self):
        result = self.run_remote(FAKE_SHA256="")
        self.assert_built_from_source(result)
        self.assertIn("SHA-256", self.reason_lines(result)[0])

    def test_given_missing_checksum_when_downloading_then_falls_back(self):
        result = self.run_remote(FAKE_SHA_DOWNLOAD="404")
        self.assert_built_from_source(result)
        self.assertIn("could not be downloaded", self.reason_lines(result)[0])

    def test_ac2_given_broken_zip_when_unpacking_then_falls_back(self):
        result = self.run_remote(FAKE_UNPACK="fail")
        self.assert_built_from_source(result)
        self.assertIn("could not unpack", self.reason_lines(result)[0])

    def test_ac2_given_bundle_without_executable_when_unpacked_then_falls_back(self):
        self.make_release_app(executable=False)
        result = self.run_remote()
        self.assert_built_from_source(result)
        self.assertIn("Contents/MacOS/Local-STT", self.reason_lines(result)[0])

    def test_ac2_given_bundle_with_non_executable_binary_when_unpacked_then_falls_back(self):
        self.make_release_app(exec_bit=False)
        result = self.run_remote()
        self.assert_built_from_source(result)
        self.assertIn("Contents/MacOS/Local-STT", self.reason_lines(result)[0])

    def test_ac2_given_fallback_without_swift_then_prints_xcode_hint(self):
        self.remove_swift()
        result = self.run_remote(FAKE_DOWNLOAD="404")
        self.assertEqual(result.returncode, 1)
        self.assertIn("xcode-select --install", result.stderr)
        self.assertEqual(self.logged("INSTALL"), [])

    # -- AC-3 ------------------------------------------------------------

    def test_ac3_given_from_source_flag_when_remote_install_then_builds_without_download(self):
        result = self.run_remote("--from-source")
        self.assert_built_from_source(result)
        self.assertFalse(any(_ZIP_URL in line for line in self.logged("curl")))
        self.assertEqual(self.logged("ditto"), [])

    def test_ac3_given_from_source_without_swift_then_prints_xcode_hint_before_any_work(self):
        self.remove_swift()
        result = self.run_remote("--from-source")
        self.assertEqual(result.returncode, 1)
        self.assertIn("xcode-select --install", result.stderr)
        self.assertEqual(self.logged("git"), [])

    def test_ac3_given_local_checkout_when_run_from_disk_then_builds_from_source(self):
        result = self.run_local()
        self.assert_built_from_source(result)
        self.assertIn("Using local checkout:", result.stdout)
        self.assertEqual(self.logged("curl"), [])
        self.assertEqual(self.logged("git"), [])

    def test_ac3_given_local_checkout_without_swift_then_prints_xcode_hint(self):
        self.remove_swift()
        result = self.run_local()
        self.assertEqual(result.returncode, 1)
        self.assertIn("xcode-select --install", result.stderr)

    # -- AC-4 ------------------------------------------------------------

    def test_ac4_given_wrong_bundle_identifier_when_verifying_then_falls_back(self):
        self.make_release_app(bundle_id="com.example.other")
        result = self.run_remote()
        self.assert_built_from_source(result)
        self.assertIn("bundle identifier is 'com.example.other'", self.reason_lines(result)[0])

    def test_ac4_given_wrong_bundle_version_when_verifying_then_falls_back(self):
        self.make_release_app(version="1.2.2")
        result = self.run_remote()
        self.assert_built_from_source(result)
        self.assertIn("bundle version is '1.2.2', expected '1.2.3'", self.reason_lines(result)[0])

    # -- AC-5 ------------------------------------------------------------

    def test_ac5_given_latest_release_redirect_when_cloning_then_checks_out_release_tag(self):
        result = self.run_remote()
        self.assert_ok(result)
        self.assertIn("curl -sI https://github.com/Advisior/local-stt/releases/latest",
                      self.logged("curl")[0])
        clone = self.logged("git clone")
        self.assertEqual(len(clone), 1)
        self.assertIn(f"--branch {_TAG} ", clone[0])

    def test_ac5_given_existing_checkout_when_updating_then_fetches_release_tag(self):
        (self.prefix / "src" / ".git").mkdir(parents=True)
        (self.prefix / "src" / "pyproject.toml").write_text(
            f'name = "local-stt"\nversion = "{_VERSION}"\n'
        )
        result = self.run_remote()
        self.assert_ok(result)
        git = self.logged("git")
        self.assertIn(f"origin {_TAG}", git[0])
        self.assertTrue(git[0].endswith(f"fetch --depth 1 origin {_TAG}"), git)
        self.assertTrue(git[1].endswith("reset --hard FETCH_HEAD"), git)

    def test_ac5_given_no_resolvable_tag_when_cloning_then_uses_main_and_fallback_applies(self):
        result = self.run_remote(FAKE_LATEST_LOCATION="", FAKE_DOWNLOAD="404")
        self.assert_built_from_source(result)
        self.assertIn("--branch main ", self.logged("git clone")[0])
        self.assertIn("using main", result.stdout)

    def test_ac5_given_garbage_location_when_resolving_then_uses_main(self):
        result = self.run_remote(
            FAKE_LATEST_LOCATION="https://github.com/Advisior/local-stt/releases/tag/v1;rm -rf"
        )
        self.assert_ok(result)
        self.assertIn("--branch main ", self.logged("git clone")[0])

    # -- AC-6 ------------------------------------------------------------

    def test_ac6_given_build_only_when_remote_install_then_builds_and_does_not_install(self):
        result = self.run_remote("--build-only")
        self.assert_ok(result)
        self.assertEqual(len(self.logged("BUILD")), 1)
        self.assertEqual(self.logged("INSTALL"), [])
        self.assertFalse(any(_ZIP_URL in line for line in self.logged("curl")))
        self.assertIn("Built (not installed):", result.stdout)

    def test_ac6_given_build_only_without_swift_then_prints_xcode_hint(self):
        self.remove_swift()
        result = self.run_remote("--build-only")
        self.assertEqual(result.returncode, 1)
        self.assertIn("xcode-select --install", result.stderr)

    # -- AC-7 ------------------------------------------------------------

    def test_ac7_given_prebuilt_install_then_python_env_xattr_and_summary_unchanged(self):
        result = self.run_remote()
        self.assert_ok(result)
        uv = self.logged("uv")
        self.assertTrue(uv[0].startswith(f"uv venv {self.prefix}/venv --python 3.12"), uv)
        self.assertIn(f"{self.prefix}/src[mlx,macos]", uv[1])
        self.assertEqual(self.logged("xattr"), ["xattr -cr /Applications/Local-STT.app"])
        self.assertEqual(self.logged("osascript"), [])
        self.assertIn("Done. Launch with: open '/Applications/Local-STT.app'", result.stdout)
        self.assertIn("Right-click the app in", result.stdout)

    # -- AC-8 ------------------------------------------------------------

    def test_ac8_given_successful_prebuilt_install_then_download_dir_removed(self):
        result = self.run_remote()
        self.assert_ok(result)
        self.assertEqual(self.leftover_download_dirs(), [])

    def test_ac8_given_failure_after_download_then_download_dir_removed(self):
        self.remove_swift()
        self.make_release_app(version="0.0.1")
        result = self.run_remote()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(self.logged("ditto")), 1)
        self.assertEqual(self.leftover_download_dirs(), [])


    # -- #63 standalone runtime -----------------------------------------

    def test_rt1_given_runtime_asset_when_remote_install_then_needs_no_git_python_or_uv(self):
        self.remove_tools("git", "uv", "swift")
        result = self.run_remote(FAKE_RUNTIME="ok")
        self.assert_ok(result)
        self.assertIn("Using standalone Python runtime v1.2.3.", result.stdout)
        self.assertTrue(any(line.endswith(_RUNTIME_URL) for line in self.logged("curl")),
                        self.stub_log())
        self.assertTrue(any(line.endswith(_RUNTIME_URL + ".sha256")
                            for line in self.logged("curl")))
        python = self.prefix / "venv" / "bin" / "python"
        self.assertTrue(python.is_file())
        self.assertEqual(self.logged("git"), [])
        self.assertEqual(self.logged("uv"), [])
        self.assertEqual(self.logged("runtime-python"),
                         ["runtime-python -I -c import claude_stt; print(claude_stt.__version__)"])
        self.assertIn("/unpacked/Local-STT.app /Applications/Local-STT.app",
                      self.logged("INSTALL")[0])
        self.assertEqual(self.leftover_download_dirs(), [])
        self.assertEqual(list(self.prefix.glob(".runtime.*")), [])

    def test_rt1_given_previous_venv_when_runtime_installs_then_replaces_it(self):
        old = self.prefix / "venv"
        (old / "bin").mkdir(parents=True)
        (old / "old-marker").write_text("x")
        result = self.run_remote(FAKE_RUNTIME="ok")
        self.assert_ok(result)
        self.assertFalse((old / "old-marker").exists())
        self.assertTrue((old / "bin" / "python").is_file())
        self.assertTrue((old / "lib" / "python3.12" / "site-packages" / "claude_stt").is_dir())

    def test_rt2_given_no_runtime_asset_then_one_reason_line_and_uv_env(self):
        result = self.run_remote(FAKE_RUNTIME="404")
        self.assert_python_env_from_uv(result)
        reasons = self.runtime_reason_lines(result)
        self.assertEqual(len(reasons), 1, result.stdout)
        self.assertIn("HTTP 404", reasons[0])
        self.assertEqual(len(self.logged("git clone")), 1)

    def test_rt2_given_network_error_then_falls_back(self):
        result = self.run_remote(FAKE_RUNTIME="network")
        self.assert_python_env_from_uv(result)
        self.assertIn("network error", self.runtime_reason_lines(result)[0])

    def test_rt2_given_checksum_mismatch_then_never_unpacks_or_runs_it(self):
        result = self.run_remote(FAKE_RUNTIME="ok", FAKE_RUNTIME_SHA256="f" * 64)
        self.assert_python_env_from_uv(result)
        self.assertIn("does not match its published SHA-256",
                      self.runtime_reason_lines(result)[0])

    def test_rt2_given_missing_or_malformed_checksum_then_falls_back(self):
        for env in ({"FAKE_RUNTIME_SHA_DOWNLOAD": "404"}, {"FAKE_RUNTIME_SHA256": "nope"}):
            with self.subTest(**env):
                self.log.write_text("")
                result = self.run_remote(FAKE_RUNTIME="ok", **env)
                self.assert_python_env_from_uv(result)
                self.assertIn("SHA-256" if "FAKE_RUNTIME_SHA256" in env else "could not be"
                              " downloaded", self.runtime_reason_lines(result)[0])

    def test_rt2_given_archive_that_does_not_unpack_then_falls_back(self):
        self.runtime_tarball.write_bytes(b"not a tarball")
        result = self.run_remote(FAKE_RUNTIME="ok", FAKE_RUNTIME_SHA256=self.runtime_sha())
        self.assert_python_env_from_uv(result)
        self.assertIn("could not unpack", self.runtime_reason_lines(result)[0])

    def test_rt2_given_archive_without_python_then_falls_back(self):
        self.make_runtime({"other/bin/python": (b"#!/bin/bash\n", 0o755)})
        result = self.run_remote(FAKE_RUNTIME="ok", FAKE_RUNTIME_SHA256=self.runtime_sha())
        self.assert_python_env_from_uv(result)
        self.assertIn("lacks an executable venv/bin/python", self.runtime_reason_lines(result)[0])

    def test_rt3_given_runtime_that_cannot_import_local_stt_then_falls_back(self):
        result = self.run_remote(FAKE_RUNTIME="ok", FAKE_RUNTIME_BROKEN="1")
        self.assert_ok(result)
        self.assertIn("could not import claude_stt", self.runtime_reason_lines(result)[0])
        self.assertTrue(self.logged("uv venv"))
        self.assertEqual(list(self.prefix.glob(".runtime.*")), [])

    def test_rt3_given_runtime_of_another_version_then_falls_back(self):
        result = self.run_remote(FAKE_RUNTIME="ok", FAKE_RUNTIME_REPORTS="9.9.9")
        self.assert_ok(result)
        self.assertIn("reports local-stt '9.9.9', expected '1.2.3'",
                      self.runtime_reason_lines(result)[0])
        self.assertTrue(self.logged("uv venv"))

    def test_rt4_given_from_source_then_runtime_not_downloaded(self):
        result = self.run_remote("--from-source", FAKE_RUNTIME="ok")
        self.assert_built_from_source(result)
        self.assertFalse(any("Local-STT-runtime" in line for line in self.logged("curl")))
        self.assertTrue(self.logged("uv venv"))

    def test_rt4_given_local_checkout_then_runtime_not_downloaded(self):
        result = self.run_local()
        self.assert_built_from_source(result)
        self.assertFalse(any("Local-STT-runtime" in line for line in self.logged("curl")))

    def test_rt4_given_no_resolvable_tag_then_runtime_not_downloaded(self):
        result = self.run_remote(FAKE_LATEST_LOCATION="", FAKE_RUNTIME="ok")
        self.assert_ok(result)
        self.assertFalse(any("Local-STT-runtime" in line for line in self.logged("curl")))
        self.assertIn("--branch main ", self.logged("git clone")[0])

    def test_rt5_given_runtime_but_no_prebuilt_app_then_clones_tag_and_builds(self):
        self.remove_tools("uv")
        result = self.run_remote(FAKE_RUNTIME="ok", FAKE_DOWNLOAD="404")
        self.assert_built_from_source(result)
        self.assertIn(f"--branch {_TAG} ", self.logged("git clone")[0])
        self.assertEqual(self.logged("uv"), [])

    def test_rt5_given_runtime_and_no_prebuilt_app_without_swift_then_xcode_hint(self):
        self.remove_tools("swift")
        result = self.run_remote(FAKE_RUNTIME="ok", FAKE_DOWNLOAD="404")
        self.assertEqual(result.returncode, 1)
        self.assertIn("xcode-select --install", result.stderr)
        self.assertEqual(self.logged("INSTALL"), [])

    def test_rt6_given_runtime_fails_and_no_uv_python_or_brew_then_explains(self):
        self.remove_tools("uv")
        result = self.run_remote(FAKE_RUNTIME="404")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(self.runtime_reason_lines(result)), 1)
        self.assertIn("need either 'uv' or a system Python", result.stderr)


if __name__ == "__main__":
    unittest.main()
