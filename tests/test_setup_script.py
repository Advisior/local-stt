import importlib.util
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "setup.py"
_spec = importlib.util.spec_from_file_location("setup_script", _SCRIPT)
setup_script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(setup_script)


def _on_platform(system: str, machine: str):
    return mock.patch.multiple(
        setup_script.platform,
        system=mock.Mock(return_value=system),
        machine=mock.Mock(return_value=machine),
    )


class DefaultEngineExtraTests(unittest.TestCase):
    def test_apple_silicon_installs_mlx(self):
        with _on_platform("Darwin", "arm64"):
            self.assertEqual(setup_script._default_engine_extra(), "mlx")

    def test_other_platforms_install_no_engine_extra(self):
        for system, machine in (
            ("Darwin", "x86_64"),
            ("Linux", "x86_64"),
            ("Linux", "aarch64"),
            ("Windows", "AMD64"),
        ):
            with self.subTest(system=system, machine=machine), _on_platform(system, machine):
                self.assertIsNone(setup_script._default_engine_extra())


if __name__ == "__main__":
    unittest.main()
