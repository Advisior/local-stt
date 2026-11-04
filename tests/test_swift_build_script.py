"""AC-21 (#55): scripts/swift-build.sh falls back to the 26.5 SDK."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "swift-build.sh"

# Fake `swift`: logs the SDKROOT it saw, fails with the SwiftUI macro error
# unless SDKROOT is set (or FAKE_SWIFT_FAIL=other forces a different error).
FAKE_SWIFT = """#!/bin/bash
echo "${SDKROOT:-<none>}" >> "$FAKE_SWIFT_LOG"
if [[ "${FAKE_SWIFT_FAIL:-}" == "other" ]]; then
    echo "error: something else broke" >&2
    exit 1
fi
if [[ -z "${SDKROOT:-}" ]]; then
    echo "error: external macro implementation type 'SwiftUIMacros.StateMacro' could not be found for macro 'State()'; plugin for module 'SwiftUIMacros' not found" >&2
    exit 1
fi
echo "Build complete"
"""


@unittest.skipIf(os.name == "nt" or shutil.which("bash") is None, "needs bash")
class SwiftBuildFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "swift"
        fake.write_text(FAKE_SWIFT)
        fake.chmod(0o755)
        self.sdk = self.tmp / "MacOSX26.5.sdk"
        self.sdk.mkdir()
        self.log = self.tmp / "calls.log"
        self.env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_SWIFT_LOG": str(self.log),
            "LOCAL_STT_FALLBACK_SDK": str(self.sdk),
        }

    def run_script(self, **extra):
        env = {**self.env, **extra}
        return subprocess.run(
            ["bash", str(SCRIPT), "build", "-c", "release"],
            env=env, capture_output=True, text=True, cwd=self.tmp,
        )

    def calls(self):
        return self.log.read_text().split()

    def test_ac21_macro_error_retries_with_fallback_sdk(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.calls(), ["<none>", str(self.sdk)])
        self.assertIn("retrying with SDKROOT", result.stdout)

    def test_ac21_explicit_sdkroot_wins(self):
        result = self.run_script(SDKROOT="/explicit.sdk")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.calls(), ["/explicit.sdk"])

    def test_ac21_missing_fallback_sdk_fails_without_retry(self):
        self.sdk.rmdir()
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), ["<none>"])
        self.assertIn("SwiftUIMacros", result.stdout)

    def test_ac21_other_errors_fail_without_retry(self):
        result = self.run_script(FAKE_SWIFT_FAIL="other")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), ["<none>"])


if __name__ == "__main__":
    unittest.main()
