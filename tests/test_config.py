import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from claude_stt.config import Config


def _on_platform(system: str, machine: str):
    return mock.patch.multiple(
        "claude_stt.config.platform",
        system=mock.Mock(return_value=system),
        machine=mock.Mock(return_value=machine),
    )


class ConfigTests(unittest.TestCase):
    def test_config_validation_clamps_invalid_values(self):
        config = Config(
            mode="bad",
            engine="nope",
            output_mode="wat",
            moonshine_model="moonshine/huge",
            max_recording_seconds=0,
            sample_rate=8000,
        ).validate()

        self.assertEqual(config.mode, "toggle")
        self.assertEqual(config.engine, "moonshine")
        self.assertEqual(config.output_mode, "auto")
        self.assertEqual(config.moonshine_model, "moonshine/huge")
        self.assertEqual(config.max_recording_seconds, 1)
        self.assertEqual(config.sample_rate, 16000)


class DefaultEngineTests(unittest.TestCase):
    def test_apple_silicon_defaults_to_mlx_large_v3_turbo(self):
        with _on_platform("Darwin", "arm64"):
            config = Config()
        self.assertEqual(config.engine, "mlx")
        self.assertEqual(config.whisper_model, "large-v3-turbo")

    def test_platforms_without_mlx_default_to_moonshine(self):
        for system, machine in (
            ("Darwin", "x86_64"),  # Intel Mac, or Python under Rosetta
            ("Linux", "x86_64"),
            ("Linux", "aarch64"),
            ("Windows", "AMD64"),
        ):
            with self.subTest(system=system, machine=machine), _on_platform(system, machine):
                config = Config()
                self.assertEqual(config.engine, "moonshine")
                self.assertEqual(config.whisper_model, "medium")


class LoadDefaultEngineTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.config_dir = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"LOCAL_STT_CONFIG_DIR": tmp.name})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("CLAUDE_PLUGIN_ROOT", None)

    def test_fresh_install_on_apple_silicon_gets_mlx(self):
        with _on_platform("Darwin", "arm64"):
            config = Config.load()
        self.assertEqual(config.engine, "mlx")
        self.assertEqual(config.whisper_model, "large-v3-turbo")

    def test_fresh_install_elsewhere_gets_moonshine(self):
        with _on_platform("Linux", "x86_64"):
            config = Config.load()
        self.assertEqual(config.engine, "moonshine")
        self.assertEqual(config.whisper_model, "medium")

    def test_existing_config_keeps_its_engine_on_apple_silicon(self):
        (self.config_dir / "config.toml").write_text(
            '[claude-stt]\nengine = "moonshine"\nwhisper_model = "medium"\n'
        )
        with _on_platform("Darwin", "arm64"):
            config = Config.load()
        self.assertEqual(config.engine, "moonshine")
        self.assertEqual(config.whisper_model, "medium")

    def test_saved_config_pins_engine_across_default_changes(self):
        with _on_platform("Linux", "x86_64"):
            self.assertTrue(Config().save())
        with _on_platform("Darwin", "arm64"):
            config = Config.load()
        self.assertEqual(config.engine, "moonshine")
        self.assertEqual(config.whisper_model, "medium")


if __name__ == "__main__":
    unittest.main()
