import os
import tempfile
import unittest
from unittest import mock

from claude_stt import daemon
from claude_stt.hotkey import _PYNPUT_AVAILABLE


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


@unittest.skipUnless(_PYNPUT_AVAILABLE, "pynput unavailable in this environment")
class UndoWiringTests(unittest.TestCase):
    """STTDaemon wires the optional undo hotkey (#45)."""

    def _daemon(self, **config):
        from claude_stt.config import Config
        from claude_stt.daemon_service import STTDaemon
        from claude_stt.hotkey import HotkeyListener

        d = STTDaemon(Config(hotkey="ctrl+shift+space", **config))
        d._hotkey = HotkeyListener(
            hotkey=d.config.hotkey, on_start=lambda: None, on_stop=lambda: None
        )
        d._overlay_send = mock.Mock()
        return d

    def _on_macos(self):
        return mock.patch("claude_stt.daemon_undo.platform.system", return_value="Darwin")

    def test_ac10_given_no_undo_hotkey_when_set_up_then_nothing_is_registered(self):
        d = self._daemon()
        with self._on_macos():
            d._setup_undo()
        self.assertEqual(len(d._hotkey._bindings), 1)
        self.assertIsNone(d._hotkey.on_other_key)
        self.assertIsNone(d._undo)

    def test_ac11_given_undo_equal_to_record_hotkey_when_set_up_then_undo_is_off(self):
        d = self._daemon(undo_hotkey="ctrl+shift+space")
        with self._on_macos(), self.assertLogs("claude_stt.daemon_service", "WARNING"):
            d._setup_undo()
        self.assertIsNone(d._undo)
        self.assertEqual(len(d._hotkey._bindings), 1)
        self.assertEqual(d._hotkey._hotkey_keys, d._hotkey._bindings[0].keys)

    def test_ac11_given_unparsable_undo_hotkey_when_set_up_then_undo_is_off(self):
        d = self._daemon(undo_hotkey="ctrl+nosuchkey")
        with self._on_macos(), self.assertLogs("claude_stt.daemon_service", "WARNING"):
            d._setup_undo()
        self.assertIsNone(d._undo)
        self.assertEqual(len(d._hotkey._bindings), 1)

    def test_given_linux_when_undo_hotkey_set_then_it_is_ignored_with_a_log(self):
        d = self._daemon(undo_hotkey="ctrl+shift+backspace")
        with mock.patch("claude_stt.daemon_undo.platform.system", return_value="Linux"), \
                self.assertLogs("claude_stt.daemon_service", "WARNING") as logs:
            d._setup_undo()
        self.assertIn("undo not supported on this platform", "\n".join(logs.output))
        self.assertIsNone(d._undo)

    def test_ac1_given_valid_undo_hotkey_when_set_up_then_binding_and_hook_are_wired(self):
        d = self._daemon(undo_hotkey="ctrl+shift+backspace", undo_window_seconds=30)
        with self._on_macos():
            d._setup_undo()
        self.assertEqual([b.label for b in d._hotkey._bindings], ["record", "undo"])
        self.assertEqual(d._hotkey.on_other_key, d._undo.invalidate)
        self.assertEqual(d._undo.window_seconds, 30)

    def _armed(self):
        d = self._daemon(undo_hotkey="ctrl+shift+backspace", sound_effects=True)
        with self._on_macos():
            d._setup_undo()
        d._undo._frontmost_app = lambda: "com.mitchellh.ghostty"
        return d

    def test_ac1_given_a_transcription_when_output_then_undo_sends_its_length(self):
        from claude_stt import daemon_service, daemon_undo
        from claude_stt.keyboard import InsertResult

        d = self._armed()
        d._engine = mock.Mock()
        d._engine.transcribe.return_value = "Hallo Welt"
        inserted = InsertResult(text="Hallo Welt. ", mode="clipboard_paste")
        audio = daemon_service.np.ones(16000, dtype="float32") * 0.1
        with mock.patch.object(daemon_service, "output_text", return_value=inserted), \
                mock.patch.object(d, "_append_history"), \
                mock.patch.object(daemon_undo, "undo_last_insert") as send:
            d._process_transcription((audio, None))
            d._on_undo_hotkey()
        send.assert_called_once_with(12)

    def test_ac3_given_an_app_switch_during_output_when_undo_in_new_app_then_nothing_sent(self):
        from claude_stt import daemon_service, daemon_undo
        from claude_stt.keyboard import InsertResult

        d = self._armed()
        d._engine = mock.Mock()
        d._engine.transcribe.return_value = "Hallo Welt"
        inserted = InsertResult(text="Hallo Welt. ", mode="clipboard_paste")
        frontmost = ["com.mitchellh.ghostty"]
        d._undo._frontmost_app = lambda: frontmost[0]

        def paste_then_switch(*_args, **_kwargs):
            frontmost[0] = "com.apple.TextEdit"
            return inserted

        audio = daemon_service.np.ones(16000, dtype="float32") * 0.1
        with mock.patch.object(daemon_service, "output_text", side_effect=paste_then_switch), \
                mock.patch.object(d, "_append_history"), \
                mock.patch.object(daemon_undo, "undo_last_insert") as send:
            d._process_transcription((audio, None))
            d._on_undo_hotkey()
        send.assert_not_called()

    def test_ac2_given_nothing_to_undo_when_hotkey_then_hint_and_warning_sound(self):
        from claude_stt import daemon_undo

        d = self._armed()
        with mock.patch.object(daemon_undo, "undo_last_insert") as send, \
                mock.patch.object(daemon_undo, "play_sound") as sound:
            d._on_undo_hotkey()
        send.assert_not_called()
        d._overlay_send.assert_called_once_with("HINT Nothing to undo")
        sound.assert_called_once_with("warning")

    def test_ac8_given_recording_when_undo_hotkey_then_it_is_ignored(self):
        from claude_stt import daemon_undo
        from claude_stt.keyboard import InsertResult

        d = self._armed()
        d._undo.record(InsertResult(text="Hallo. ", mode="clipboard_paste"), d._undo.begin_insert())
        d._recording = True
        with mock.patch.object(daemon_undo, "undo_last_insert") as send:
            d._on_undo_hotkey()
        send.assert_not_called()
        d._overlay_send.assert_not_called()
        self.assertTrue(d._recording)


if __name__ == "__main__":
    unittest.main()
