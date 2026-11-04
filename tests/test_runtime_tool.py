"""Tests for scripts/runtime_tool.py and the runtime locks (#63)."""

import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "runtime_tool.py"
_spec = importlib.util.spec_from_file_location("runtime_tool", _SCRIPT)
runtime_tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runtime_tool)

_RUNTIME_DIR = _ROOT / "scripts" / "runtime"


def _write_wheel(site: Path, dist: str, *tags: str) -> None:
    info = site / f"{dist}.dist-info"
    info.mkdir(parents=True)
    lines = ["Wheel-Version: 1.0", "Generator: test", "Root-Is-Purelib: false"]
    lines += [f"Tag: {tag}" for tag in tags]
    (info / "WHEEL").write_text("\n".join(lines) + "\n")


@unittest.skipIf(sys.platform == "win32", "the runtime is macOS only; needs symlinks")
class RelocateScriptsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()

    def write(self, name, text, mode=0o755):
        path = self.bin / name
        path.write_text(text)
        path.chmod(mode)
        return path

    def test_given_absolute_python_shebang_then_replaced_by_trampoline(self):
        script = self.write(
            "local-stt",
            "#!/Users/runner/work/dist/runtime/venv/bin/python3.12\n"
            "# -*- coding: utf-8 -*-\nimport sys\n",
        )
        self.assertEqual(runtime_tool.relocate_scripts(self.bin), ["local-stt"])
        text = script.read_text()
        self.assertTrue(text.startswith(runtime_tool.TRAMPOLINE))
        self.assertTrue(text.endswith("# -*- coding: utf-8 -*-\nimport sys\n"))
        self.assertNotIn("/Users/runner", text)
        self.assertEqual(script.stat().st_mode & 0o777, 0o755)

    def test_given_other_files_then_left_alone(self):
        sh = self.write("pip3", "#!/bin/sh\necho hi\n")
        env = self.write("tool", "#!/usr/bin/env python3\nprint(1)\n")
        binary = self.bin / "python3.12"
        binary.write_bytes(b"\xcf\xfa\xed\xfe binary")
        (self.bin / "python3").symlink_to("python3.12")
        no_newline = self.write("odd", "#!/opt/x/bin/python3")
        self.assertEqual(runtime_tool.relocate_scripts(self.bin), [])
        self.assertEqual(sh.read_text(), "#!/bin/sh\necho hi\n")
        self.assertEqual(env.read_text(), "#!/usr/bin/env python3\nprint(1)\n")
        self.assertEqual(no_newline.read_text(), "#!/opt/x/bin/python3")

    def test_given_relocated_script_when_moved_then_runs_python_next_to_it(self):
        moved = self.tmp / "moved dir with space" / "bin"
        moved.parent.mkdir()
        self.write(
            "hello",
            "#!/build/somewhere/bin/python3\nimport sys\nprint('ran', sys.argv[1:])\n",
        )
        (self.bin / "python3").symlink_to(sys.executable)
        runtime_tool.relocate_scripts(self.bin)
        self.bin.rename(moved)
        result = subprocess.run(
            [str(moved / "hello"), "a b", "c"], capture_output=True, text=True, timeout=30
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ran ['a b', 'c']")


class MacosTagTests(unittest.TestCase):
    def setUp(self):
        self.site = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.site, True)

    def test_platform_fits(self):
        fits = runtime_tool.platform_fits
        self.assertTrue(fits("any", (13, 0)))
        self.assertTrue(fits("macosx_13_0_arm64", (13, 0)))
        self.assertTrue(fits("macosx_11_0_arm64", (13, 0)))
        self.assertTrue(fits("macosx_10_9_universal2", (13, 0)))
        self.assertFalse(fits("macosx_14_0_arm64", (13, 0)))
        self.assertFalse(fits("macosx_15_0_arm64", (13, 0)))
        self.assertFalse(fits("macosx_12_0_x86_64", (13, 0)))
        self.assertFalse(fits("manylinux_2_35_x86_64", (13, 0)))

    def test_given_only_fitting_wheels_then_no_violation(self):
        _write_wheel(self.site, "mlx-0.29.3", "cp312-cp312-macosx_13_0_arm64")
        _write_wheel(self.site, "tqdm-4.0", "py3-none-any")
        _write_wheel(self.site, "pyobjc_core-12", "cp312-cp312-macosx_10_13_universal2")
        self.assertEqual(runtime_tool.macos_tag_violations(self.site, (13, 0)), [])

    def test_given_macos15_wheel_then_reported(self):
        _write_wheel(self.site, "mlx-0.29.3", "cp312-cp312-macosx_15_0_arm64")
        violations = runtime_tool.macos_tag_violations(self.site, (13, 0))
        self.assertEqual(len(violations), 1)
        self.assertIn("mlx-0.29.3.dist-info: cp312-cp312-macosx_15_0_arm64", violations[0])

    def test_given_wheel_with_several_tags_then_one_fitting_tag_is_enough(self):
        _write_wheel(self.site, "x-1", "py2-none-macosx_15_0_arm64", "py3-none-macosx_12_0_arm64")
        self.assertEqual(runtime_tool.macos_tag_violations(self.site, (13, 0)), [])

    def test_cli_exit_codes(self):
        _write_wheel(self.site, "ok-1", "py3-none-any")
        self.assertEqual(runtime_tool.main(["check-macos-tags", str(self.site), "--max", "13.0"]),
                         0)
        _write_wheel(self.site, "bad-1", "cp312-cp312-macosx_14_0_arm64")
        self.assertEqual(runtime_tool.main(["check-macos-tags", str(self.site), "--max", "13.0"]),
                         1)

    def test_cli_given_empty_site_packages_then_fails(self):
        self.assertEqual(runtime_tool.main(["check-macos-tags", str(self.site), "--max", "13.0"]),
                         1)

    def test_parse_version_rejects_garbage(self):
        with self.assertRaises(ValueError):
            runtime_tool.parse_version("13")


def _locked(path: Path) -> dict[str, list[str]]:
    """Maps each pinned name to its hashes."""
    pins: dict[str, list[str]] = {}
    current = None
    for line in path.read_text().splitlines():
        match = re.match(r"^([A-Za-z0-9._-]+)==(\S+)", line)
        if match:
            current = match.group(1).lower().replace("_", "-")
            pins[current] = []
        elif current and "--hash=sha256:" in line:
            pins[current].append(line.split("--hash=sha256:")[1].split()[0])
        elif line and not line.startswith(" "):
            current = None
    return pins


def _requirement_name(spec: str) -> str:
    return re.match(r"[A-Za-z0-9._-]+", spec).group(0).lower().replace("_", "-")


class RuntimeLockTests(unittest.TestCase):
    def test_every_pin_carries_sha256_hashes(self):
        for name in ("requirements.txt", "build-requirements.txt"):
            pins = _locked(_RUNTIME_DIR / name)
            self.assertTrue(pins, name)
            for package, hashes in pins.items():
                self.assertTrue(hashes, f"{name}: {package} has no hash")
                for digest in hashes:
                    self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_runtime_lock_covers_project_dependencies_and_extras(self):
        project = tomllib.loads((_ROOT / "pyproject.toml").read_text())["project"]
        wanted = list(project["dependencies"])
        for extra in ("mlx", "macos"):
            wanted += project["optional-dependencies"][extra]
        pins = _locked(_RUNTIME_DIR / "requirements.txt")
        for spec in wanted:
            self.assertIn(_requirement_name(spec), pins, f"run: bash scripts/lock-runtime.sh ({spec})")

    def test_build_lock_has_hatchling_from_pyproject(self):
        backend = tomllib.loads((_ROOT / "pyproject.toml").read_text())["build-system"]
        for spec in backend["requires"]:
            self.assertIn(_requirement_name(spec),
                          _locked(_RUNTIME_DIR / "build-requirements.txt"))


class PythonPinTests(unittest.TestCase):
    def test_pin_file_has_exact_version_and_checksum(self):
        pins = {}
        for line in (_RUNTIME_DIR / "python-build-standalone.env").read_text().splitlines():
            if line and not line.startswith("#"):
                key, _, value = line.partition("=")
                pins[key] = value
        self.assertRegex(pins["PBS_RELEASE"], r"^\d{8}$")
        self.assertRegex(pins["PYTHON_VERSION"], r"^3\.12\.\d+$")
        self.assertRegex(pins["PBS_SHA256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            pins["PBS_ASSET"],
            f"cpython-{pins['PYTHON_VERSION']}+{pins['PBS_RELEASE']}"
            "-aarch64-apple-darwin-install_only_stripped.tar.gz",
        )


if __name__ == "__main__":
    unittest.main()
