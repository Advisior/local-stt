import os
import tempfile
import unittest
from unittest import mock

from claude_stt import daemon


class DaemonPidTests(unittest.TestCase):
    def test_pid_file_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["CLAUDE_STT_CONFIG_DIR"] = temp_dir
            try:
                daemon._write_pid_file(os.getpid())
                data = daemon._read_pid_file()
                self.assertIsNotNone(data)
                self.assertEqual(data["pid"], os.getpid())
                self.assertIn("command", data)
                self.assertIn("created_at", data)
            finally:
                os.environ.pop("CLAUDE_STT_CONFIG_DIR", None)

    def test_pid_file_legacy_format(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["CLAUDE_STT_CONFIG_DIR"] = temp_dir
            try:
                pid_path = daemon.get_pid_file()
                pid_path.parent.mkdir(parents=True, exist_ok=True)
                pid_path.write_text(str(os.getpid()))
                data = daemon._read_pid_file()
                self.assertIsNotNone(data)
                self.assertEqual(data["pid"], os.getpid())
            finally:
                os.environ.pop("CLAUDE_STT_CONFIG_DIR", None)

    def test_stale_pid_file_removed_when_not_claude_stt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["CLAUDE_STT_CONFIG_DIR"] = temp_dir
            original_get_process_command = daemon._get_process_command
            try:
                daemon._write_pid_file(os.getpid())
                daemon._get_process_command = lambda pid: "python other-process"
                self.assertFalse(daemon.is_daemon_running())
                self.assertFalse(daemon.get_pid_file().exists())
            finally:
                daemon._get_process_command = original_get_process_command
                os.environ.pop("CLAUDE_STT_CONFIG_DIR", None)


class SpawnBackgroundOfflineModeTests(unittest.TestCase):
    """The spawned daemon runs offline only once its model is cached."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        env = {k: v for k, v in os.environ.items() if k != "HF_HUB_OFFLINE"}
        env["CLAUDE_STT_CONFIG_DIR"] = self.temp_dir.name
        env_patch = mock.patch.dict(os.environ, env, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.popen = mock.Mock()
        for patcher in (
            mock.patch.object(daemon.subprocess, "Popen", self.popen),
            mock.patch.object(daemon, "is_daemon_running", return_value=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _spawn_env(self, model_cached: bool) -> dict:
        with mock.patch.object(daemon, "_model_is_cached", return_value=model_cached):
            self.assertTrue(daemon._spawn_background())
        return self.popen.call_args.kwargs["env"]

    def test_offline_when_model_is_cached(self):
        self.assertEqual(self._spawn_env(model_cached=True).get("HF_HUB_OFFLINE"), "1")

    def test_online_when_model_is_missing(self):
        # A fresh install has to download the model on its first start.
        self.assertNotIn("HF_HUB_OFFLINE", self._spawn_env(model_cached=False))

    def test_explicit_setting_wins(self):
        os.environ["HF_HUB_OFFLINE"] = "0"
        self.assertEqual(self._spawn_env(model_cached=True)["HF_HUB_OFFLINE"], "0")


class ModelIsCachedTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        env_patch = mock.patch.dict(os.environ, {"CLAUDE_STT_CONFIG_DIR": self.temp_dir.name})
        env_patch.start()
        self.addCleanup(env_patch.stop)

    def test_asks_the_configured_engine(self):
        engine = mock.Mock()
        engine.is_model_cached.return_value = True
        with mock.patch.object(daemon, "build_engine", return_value=engine):
            self.assertTrue(daemon._model_is_cached())

    def test_probe_failure_means_not_cached(self):
        with mock.patch.object(daemon, "build_engine", side_effect=RuntimeError("boom")):
            self.assertFalse(daemon._model_is_cached())


if __name__ == "__main__":
    unittest.main()
