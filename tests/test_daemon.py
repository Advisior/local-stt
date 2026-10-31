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


class AudioRecoveryTests(unittest.TestCase):
    """STTDaemon recovers a dead or switched input stream (#44)."""

    HINT = "HINT No microphone input. Check the input device."

    def _daemon(self, **config):
        from claude_stt.config import Config
        from claude_stt.daemon_service import STTDaemon

        config.setdefault("sound_effects", True)
        d = STTDaemon(Config(**config))
        d._recorder = mock.Mock()
        d._recorder.device_name.return_value = "AirPods"
        d._overlay_send = mock.Mock()
        for target in ("claude_stt.daemon_service.play_sound", "claude_stt.daemon_audio.play_sound"):
            patcher = mock.patch(target)
            setattr(self, "sound_" + target.split(".")[1], patcher.start())
            self.addCleanup(patcher.stop)
        patcher = mock.patch("claude_stt.daemon_service.get_active_window", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        return d

    def _recording(self, d, elapsed=3.0):
        d._recording = True
        d._record_start_time = __import__("time").time() - elapsed

    def test_ac3_given_the_start_reopen_fails_when_recording_starts_then_hint_error_sound_and_warning(self):
        d = self._daemon()
        d._recorder.start.return_value = False
        with self.assertLogs("claude_stt.daemon_audio", "WARNING") as logs:
            d._on_recording_start()
        self.assertFalse(d._recording)
        d._overlay_send.assert_called_once_with(self.HINT)
        self.sound_daemon_audio.assert_called_once_with("error")
        self.assertIn("AirPods", "\n".join(logs.output))

    def test_ac3_given_sound_effects_off_when_no_input_then_no_error_sound(self):
        d = self._daemon(sound_effects=False)
        d._recorder.start.return_value = False
        with self.assertLogs("claude_stt.daemon_audio", "WARNING"):
            d._on_recording_start()
        self.sound_daemon_audio.assert_not_called()
        d._overlay_send.assert_called_once_with(self.HINT)

    def test_ac2_given_a_recoverable_gap_when_watchdog_runs_then_recording_continues(self):
        d = self._daemon()
        self._recording(d)
        d._recorder.ensure_alive.return_value = True
        d._check_audio_stream()
        self.assertTrue(d._recording)
        d._recorder.stop.assert_not_called()
        d._overlay_send.assert_not_called()

    def test_ac3_given_the_stream_stays_dead_when_watchdog_runs_then_recording_ends_with_hint(self):
        d = self._daemon()
        self._recording(d)
        d._recorder.ensure_alive.return_value = False
        d._recorder.stop.return_value = None
        with self.assertLogs("claude_stt.daemon_audio", "WARNING") as logs:
            d._check_audio_stream()
        self.assertFalse(d._recording)
        d._recorder.stop.assert_called_once()
        d._overlay_send.assert_called_once_with(self.HINT)
        self.sound_daemon_audio.assert_called_once_with("error")
        self.assertIn("No microphone input from AirPods", "\n".join(logs.output))
        self.assertTrue(d._transcribe_queue.empty())

    def test_ac3_given_audio_before_the_drop_when_recording_ends_then_it_is_still_transcribed(self):
        import numpy as np

        d = self._daemon()
        self._recording(d)
        d._recorder.ensure_alive.return_value = False
        d._recorder.stop.return_value = np.ones(16000, dtype="float32")
        with self.assertLogs("claude_stt.daemon_audio", "WARNING"):
            d._check_audio_stream()
        self.assertEqual(d._transcribe_queue.qsize(), 1)

    def test_given_no_recording_when_watchdog_runs_then_recorder_is_not_touched(self):
        d = self._daemon()
        d._check_audio_stream()
        d._recorder.ensure_alive.assert_not_called()

    def test_ac4_given_a_recording_without_audio_when_it_stops_then_warning_then_reopen(self):
        d = self._daemon()
        self._recording(d)
        d._recorder.stop.return_value = None
        manager = mock.Mock()
        d._logger = manager.logger
        d._recorder.reopen = manager.reopen
        d._on_recording_stop()
        names = [name for name, _args, _kwargs in manager.mock_calls]
        self.assertLess(names.index("logger.warning"), names.index("reopen"))

    def test_ac4_given_a_recording_with_audio_when_it_stops_then_no_reopen(self):
        import numpy as np

        d = self._daemon()
        self._recording(d)
        d._recorder.stop.return_value = np.ones(16000, dtype="float32")
        d._on_recording_stop()
        d._recorder.reopen.assert_not_called()

    def test_ac9_given_a_too_short_recording_when_it_stops_then_skipped_and_restarted(self):
        d = self._daemon(min_recording_seconds=1.0)
        self._recording(d, elapsed=0.2)
        with mock.patch("claude_stt.daemon_service.threading.Timer") as timer:
            d._on_recording_stop()
        timer.assert_called_once_with(0.3, d._on_recording_start)
        d._recorder.stop.assert_not_called()
        d._recorder.reopen.assert_not_called()

    def _poll(self, d, device_ids, step=2.0):
        from claude_stt import daemon_audio

        clock = self.__dict__.setdefault("_clock", [1000.0])
        with mock.patch.object(daemon_audio, "default_input_device_id", side_effect=device_ids) as probe, \
                mock.patch.object(daemon_audio.time, "monotonic", side_effect=lambda: clock[0]):
            for _ in device_ids:
                d._check_default_input()
                clock[0] += step
        return probe

    def test_ac5_given_unset_audio_device_when_default_input_changes_then_stream_reopens(self):
        d = self._daemon()
        with self.assertLogs("claude_stt.daemon_audio", "INFO") as logs:
            self._poll(d, [71, 71, 85])
        d._recorder.reopen.assert_called_once_with()
        self.assertIn("Default input changed", "\n".join(logs.output))

    def test_ac5_given_the_reopen_fails_when_default_changed_then_the_next_poll_retries(self):
        d = self._daemon()
        d._recorder.reopen.side_effect = [False, True]
        with self.assertLogs("claude_stt.daemon_audio", "INFO"):
            self._poll(d, [71, 85, 85, 85])
        self.assertEqual(d._recorder.reopen.call_count, 2)

    def test_ac3_given_the_stream_stays_dead_when_partial_audio_is_queued_then_its_duration_is_recorded(self):
        import numpy as np

        d = self._daemon()
        d._last_duration_s = 9.9  # from an earlier dictation
        self._recording(d, elapsed=3.0)
        d._recorder.ensure_alive.return_value = False
        d._recorder.stop.return_value = np.ones(1600, dtype=np.float32)
        with self.assertLogs("claude_stt.daemon_audio", "WARNING"):
            d._check_audio_stream()
        self.assertAlmostEqual(d._last_duration_s, 3.0, delta=0.5)
        self.assertEqual(d._transcribe_queue.qsize(), 1)

    def test_ac5_given_checks_closer_than_2s_when_polled_then_coreaudio_is_asked_once(self):
        d = self._daemon()
        probe = self._poll(d, [71, 85, 85], step=0.5)
        self.assertEqual(probe.call_count, 1)
        d._recorder.reopen.assert_not_called()

    def test_ac5_given_a_running_recording_when_default_changes_then_no_reopen_until_it_ends(self):
        d = self._daemon()
        self._poll(d, [71])
        d._recording = True
        self._poll(d, [85])
        d._recorder.reopen.assert_not_called()
        d._recording = False
        self._poll(d, [85])
        d._recorder.reopen.assert_called_once_with()

    def test_ac6_given_the_check_fails_when_polled_then_it_is_skipped(self):
        d = self._daemon()
        self._poll(d, [None, None, 85, None, 85])
        d._recorder.reopen.assert_not_called()

    def test_ac8_given_a_configured_audio_device_when_polled_then_coreaudio_is_not_asked(self):
        d = self._daemon(audio_device=3)
        probe = self._poll(d, [71, 85])
        probe.assert_not_called()
        d._recorder.reopen.assert_not_called()

    def test_ac3_given_mute_on_record_when_start_fails_then_sound_is_restored_before_the_error_sound(self):
        d = self._daemon(mute_on_record=True)
        d._recorder.start.return_value = False
        manager = mock.Mock()
        d._mute_system_audio = manager.mute
        d._restore_system_audio = manager.restore
        self.sound_daemon_audio.side_effect = manager.play_sound
        with self.assertLogs("claude_stt.daemon_audio", "WARNING"):
            d._on_recording_start()
        names = [name for name, _args, _kwargs in manager.mock_calls]
        self.assertEqual(names, ["mute", "restore", "play_sound"])

    def test_ac5_given_the_default_changes_after_startup_when_first_polled_then_stream_reopens(self):
        from claude_stt import daemon_audio

        d = self._daemon()
        d._engine = mock.Mock()
        d._hotkey = mock.Mock()
        d._hotkey.start.return_value = False
        order = []
        d._recorder.prewarm.side_effect = lambda: order.append("prewarm")

        def probe():
            order.append("probe")
            return 71

        with mock.patch.object(d, "_init_components", return_value=True), \
                mock.patch.object(d, "_start_overlay"), \
                mock.patch.object(daemon_audio, "default_input_device_id", side_effect=probe), \
                self.assertRaises(SystemExit):
            d.run()
        self.assertEqual(order, ["probe", "prewarm"])
        self._poll(d, [85])
        d._recorder.reopen.assert_called_once_with()
