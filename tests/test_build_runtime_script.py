"""Tests for scripts/build-runtime.sh with curl, uname and the CPython stubbed (#63).

The script logic (pin checks, checksum refusal, pip flags, relocation check,
packaging) runs for real against a fake python-build-standalone tarball whose
python3 is a bash stub. Building the real runtime needs macOS arm64 (CI).
"""

import hashlib
import io
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_VERSION = "1.2.3"
_PY_VERSION = "3.12.13"
_RELEASE = "20260718"
_ASSET = f"cpython-{_PY_VERSION}+{_RELEASE}-aarch64-apple-darwin-install_only_stripped.tar.gz"
_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    f"{_RELEASE}/cpython-{_PY_VERSION}%2B{_RELEASE}"
    "-aarch64-apple-darwin-install_only_stripped.tar.gz"
)
_OUT = f"Local-STT-runtime-v{_VERSION}-macos-arm64.tar.gz"

_REAL_TOOLS = (
    "bash", "basename", "cat", "chmod", "cp", "dirname", "find", "gzip", "head", "ln", "mkdir",
    "mktemp", "mv", "rm", "sed", "shasum", "tar", "touch", "tr", "wc",
)

_STUBS = {
    "uname": """
        case "$1" in
            -s) echo "${FAKE_OS:-Darwin}" ;;
            -m) echo "${FAKE_ARCH:-arm64}" ;;
        esac
    """,
    "curl": """
        echo "curl $*" >> "$STUB_LOG"
        out=""
        while [[ $# -gt 0 ]]; do
            if [[ "$1" == "-o" ]]; then out="$2"; shift; fi
            shift
        done
        cp "$FAKE_PBS_TARBALL" "$out"
    """,
}

# Stand-in for the CPython in the PBS tarball.
_FAKE_PYTHON = r"""#!/bin/bash
self="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
all="$*"
echo "python $0 ${all//$'\n'/ }" >> "$STUB_LOG"
[[ "$1" == "-I" ]] && shift
case "$1" in
    -c)
        case "$2" in
            *version_info*) echo "$FAKE_PY_VERSION" ;;
            *) [[ -z "${FAKE_SMOKE_FAIL:-}" ]] || exit 1
               echo "$FAKE_VERSION" ;;
        esac
        ;;
    -m)
        shift
        if [[ "$1" == "venv" ]]; then
            mkdir -p "$2/bin"
            ln -s "$self" "$2/bin/python"
            exit 0
        fi
        args=("$@")
        wheel_dir="" target="" no_deps=""
        for ((i = 0; i < ${#args[@]}; i++)); do
            case "${args[$i]}" in
                -w) wheel_dir="${args[$((i + 1))]}" ;;
                --target) target="${args[$((i + 1))]}" ;;
                --no-deps) no_deps=1 ;;
            esac
        done
        if [[ -n "$wheel_dir" ]]; then
            mkdir -p "$wheel_dir"
            touch "$wheel_dir/local_stt-$FAKE_VERSION-py3-none-any.whl"
        elif [[ -n "$target" ]]; then
            mkdir -p "$target/bin" "$target/fake-1.0.dist-info"
            printf 'Tag: %s\n' "$FAKE_WHEEL_TAG" > "$target/fake-1.0.dist-info/WHEEL"
        elif [[ -n "$no_deps" && "${args[*]}" == *install* ]]; then
            printf '#!%s\nimport sys\n' "$self" > "$(dirname "$self")/local-stt"
            chmod +x "$(dirname "$self")/local-stt"
        fi
        ;;
    *.py) exec "$REAL_PYTHON" -I "$@" ;;
esac
"""


def _write_exec(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _fake_pbs_tarball(path: Path) -> None:
    with tarfile.open(path, "w:gz") as tar:
        def add(name, data=b"", mode=0o644, kind=tarfile.REGTYPE):
            info = tarfile.TarInfo(name)
            info.type = kind
            info.mode = mode if kind == tarfile.REGTYPE else 0o755
            info.size = len(data) if kind == tarfile.REGTYPE else 0
            tar.addfile(info, io.BytesIO(data) if kind == tarfile.REGTYPE else None)

        add("python", kind=tarfile.DIRTYPE)
        add("python/bin", kind=tarfile.DIRTYPE)
        add("python/bin/python3", _FAKE_PYTHON.encode(), mode=0o755)
        add("python/lib/python3.12/site-packages", kind=tarfile.DIRTYPE)
        add("python/lib/python3.12/site-packages/README.txt", b"site\n")


@unittest.skipIf(sys.platform == "win32", "build-runtime.sh is a bash script for macOS")
class BuildRuntimeScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.log = self.tmp / "stub.log"
        self.log.touch()
        self.tmpdir = self.tmp / "tmpdir"
        self.tmpdir.mkdir()

        for tool in _REAL_TOOLS:
            real = shutil.which(tool)
            self.assertIsNotNone(real, f"missing real tool {tool}")
            (self.bin / tool).symlink_to(real)
        for name, body in _STUBS.items():
            _write_exec(self.bin / name, "#!/bin/bash\n" + textwrap.dedent(body))

        self.repo = self.tmp / "repo"
        scripts = self.repo / "scripts"
        scripts.mkdir(parents=True)
        shutil.copy(_ROOT / "scripts" / "build-runtime.sh", scripts)
        shutil.copy(_ROOT / "scripts" / "runtime_tool.py", scripts)
        shutil.copytree(_ROOT / "scripts" / "runtime", scripts / "runtime")
        (self.repo / "pyproject.toml").write_text(
            f'name = "local-stt"\nversion = "{_VERSION}"\n'
        )
        self.tarball = self.tmp / "pbs.tar.gz"
        _fake_pbs_tarball(self.tarball)
        self.write_pins(sha=hashlib.sha256(self.tarball.read_bytes()).hexdigest())

        self.env = {
            "PATH": str(self.bin),
            "HOME": str(self.tmp / "home"),
            "TMPDIR": str(self.tmpdir),
            "STUB_LOG": str(self.log),
            "REAL_PYTHON": sys.executable,
            "FAKE_PBS_TARBALL": str(self.tarball),
            "FAKE_VERSION": _VERSION,
            "FAKE_PY_VERSION": _PY_VERSION,
            "FAKE_WHEEL_TAG": "cp312-cp312-macosx_13_0_arm64",
        }

    def write_pins(self, sha, release=_RELEASE, py=_PY_VERSION, asset=_ASSET):
        (self.repo / "scripts" / "runtime" / "python-build-standalone.env").write_text(
            "# test pins\n"
            f"PBS_RELEASE={release}\nPYTHON_VERSION={py}\nPBS_ASSET={asset}\nPBS_SHA256={sha}\n"
        )

    def run_build(self, **env):
        return subprocess.run(
            ["bash", str(self.repo / "scripts" / "build-runtime.sh")],
            cwd=self.tmp,
            env={**self.env, **env},
            capture_output=True,
            text=True,
            timeout=60,
        )

    def logged(self, prefix):
        return [line for line in self.log.read_text().splitlines() if line.startswith(prefix)]

    def out(self, name=_OUT):
        return self.repo / "dist" / name

    def assert_failed_without_asset(self, result):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertFalse(self.out().exists())
        self.assertFalse(self.out(_OUT + ".sha256").exists())
        self.assertEqual(list(self.tmpdir.iterdir()), [])

    # -- happy path ------------------------------------------------------

    def test_given_pinned_tarball_when_building_then_writes_runtime_and_checksum(self):
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        curl = self.logged("curl")
        self.assertEqual(len(curl), 1, curl)
        self.assertTrue(curl[0].startswith(f"curl -fsSL --retry 3 -o {self.tmpdir}/"), curl)
        self.assertTrue(curl[0].endswith(f"/{_ASSET} {_URL}"), curl)

        with tarfile.open(self.out()) as tar:
            names = tar.getnames()
        self.assertTrue(all(n == "venv" or n.startswith("venv/") for n in names), names)
        self.assertIn("venv/bin/python", names)
        self.assertIn("venv/bin/local-stt", names)
        self.assertNotIn("venv/lib/python3.12/site-packages/bin", names)

        digest = hashlib.sha256(self.out().read_bytes()).hexdigest()
        self.assertEqual(self.out(_OUT + ".sha256").read_text(), f"{digest}  {_OUT}\n")
        self.assertEqual(list(self.tmpdir.iterdir()), [], "work dir left behind")

    def test_pip_installs_only_hash_locked_macos13_wheels(self):
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        pip = [line for line in self.logged("python") if " -m pip " in line]
        build_deps = [line for line in pip if "build-requirements.txt" in line]
        self.assertEqual(len(build_deps), 1)
        self.assertIn("--require-hashes --only-binary :all:", build_deps[0])
        self.assertIn("buildenv", "\n".join(self.logged("python")))
        wheel = [line for line in pip if " wheel " in line]
        self.assertIn("--no-deps --no-build-isolation --no-index", wheel[0])
        deps = [line for line in pip if "runtime/requirements.txt" in line]
        self.assertEqual(len(deps), 1)
        for flag in ("--require-hashes", "--only-binary :all:", "--platform macosx_13_0_arm64",
                     "--implementation cp", "--python-version 3.12", "--abi cp312",
                     "--target "):
            self.assertIn(flag, deps[0])
        own = [line for line in pip if f"local_stt-{_VERSION}-py3-none-any.whl" in line]
        self.assertIn("install --no-deps --no-index", own[0])
        self.assertTrue(any(line.endswith("pip --disable-pip-version-check --no-input check")
                            for line in pip), pip)

    def test_console_scripts_are_relocatable_and_smoke_runs_from_moved_dir(self):
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        script = self.repo / "dist" / "runtime" / "venv" / "bin" / "local-stt"
        self.assertTrue(script.read_text().startswith("#!/bin/sh\n'''exec'"))
        moved = [line for line in self.logged("python") if "relocation check with spaces" in line]
        self.assertTrue(any("import claude_stt" in line for line in moved), moved)
        self.assertTrue(any("--help" in line for line in moved), moved)

    # -- refusals --------------------------------------------------------

    def test_given_checksum_mismatch_then_refuses_before_unpacking_or_running(self):
        self.write_pins(sha="0" * 64)
        result = self.run_build()
        self.assert_failed_without_asset(result)
        self.assertIn("refusing to use it", result.stderr)
        self.assertEqual(self.logged("python"), [])
        self.assertFalse((self.repo / "dist" / "runtime").exists())

    def test_given_malformed_pin_then_refuses_before_download(self):
        for kwargs in ({"sha": "abc"}, {"sha": "0" * 64, "release": "latest"},
                       {"sha": "0" * 64, "py": "3.12"},
                       {"sha": "0" * 64, "asset": "cpython-3.12.13-other.tar.gz"}):
            with self.subTest(**kwargs):
                self.write_pins(**kwargs)
                result = self.run_build()
                self.assert_failed_without_asset(result)
                self.assertEqual(self.logged("curl"), [])

    def test_given_linux_or_intel_then_refuses(self):
        for env in ({"FAKE_OS": "Linux"}, {"FAKE_ARCH": "x86_64"}):
            with self.subTest(**env):
                result = self.run_build(**env)
                self.assertEqual(result.returncode, 1)
                self.assertIn("macOS arm64 only", result.stderr)
                self.assertEqual(self.logged("curl"), [])

    def test_given_wrong_python_version_in_tarball_then_fails(self):
        result = self.run_build(FAKE_PY_VERSION="3.12.1")
        self.assert_failed_without_asset(result)
        self.assertIn("runtime reports Python 3.12.1", result.stderr)

    def test_given_wheel_for_newer_macos_then_fails(self):
        result = self.run_build(FAKE_WHEEL_TAG="cp312-cp312-macosx_15_0_arm64")
        self.assert_failed_without_asset(result)
        self.assertIn("macosx_15_0_arm64", result.stderr)

    def test_given_relocated_runtime_cannot_import_then_fails(self):
        result = self.run_build(FAKE_SMOKE_FAIL="1")
        self.assert_failed_without_asset(result)
        self.assertIn("relocated runtime failed its import check", result.stderr)
        self.assertTrue((self.repo / "dist" / "runtime" / "venv" / "bin" / "python3").exists(),
                        "runtime not moved back after the check")


if __name__ == "__main__":
    unittest.main()
