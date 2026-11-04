"""Daemon side of the recording HUD (#60): cancel, level, private flag, done text."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from claude_stt import daemon_service, history, recorder
from claude_stt.config import Config
from claude_stt.keyboard import InsertResult
from claude_stt.recorder import AudioRecorder, RecorderConfig


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.config_dir = Path(self._tmp.name)
        env = mock.patch.dict(os.environ, {"CLAUDE_STT_CONFIG_DIR": self._tmp.name})
        env.start()
        self.addCleanup(env.stop)
        self.sent = []

    def _daemon(self, **config):
        d = daemon_service.STTDaemon(Config(sound_effects=False, **config))
        d._overlay_send = self.sent.append
        d._recorder = mock.Mock()
        d._recorder.start.return_value = True
        d._recorder.stop.return_value = np.full(16000, 0.1, dtype=np.float32)
        d._recorder.current_level.return_value = 0.42
        d._hotkey = mock.Mock()
        d._hotkey.cancel_armed = False
        return d


class CancelTests(_Base):
    def _start(self, d):
        with mock.patch.object(daemon_service, "get_active_window", return_value=None):
            d._on_recording_start()

    def test_ac8_given_recording_when_cancelled_then_audio_is_dropped_and_overlay_hides(self):
        d = self._daemon()
        self._start(d)
        self.assertTrue(d._hotkey.cancel_armed)
        with self.assertLogs("claude_stt", "INFO") as logs:
            d._on_recording_cancel()
        self.assertFalse(d._recording)
        self.assertFalse(d._hotkey.cancel_armed)
        d._recorder.stop.assert_called_once_with()
        self.assertTrue(d._transcribe_queue.empty())
        self.assertEqual(self.sent[-1], "CANCEL")
        self.assertIn("Recording cancelled", "\n".join(logs.output))

    def test_ac8_given_mute_on_record_when_cancelled_then_audio_is_restored(self):
        d = self._daemon(mute_on_record=True)
        d._mute_system_audio = mock.Mock()
        d._restore_system_audio = mock.Mock()
        self._start(d)
        d._on_recording_cancel()
        d._restore_system_audio.assert_called_once_with()

    def test_ac8_given_not_recording_when_cancelled_then_nothing_happens(self):
        d = self._daemon()
        d._on_recording_cancel()
        d._recorder.stop.assert_not_called()
        self.assertEqual(self.sent, [])

    def test_ac9_given_recording_stops_normally_then_cancel_is_disarmed(self):
        d = self._daemon()
        self._start(d)
        d._on_recording_stop()
        self.assertFalse(d._hotkey.cancel_armed)

    def test_ac9_given_start_fails_then_cancel_stays_disarmed(self):
        d = self._daemon()
        d._recorder.start.return_value = False
        with self.assertLogs("claude_stt", "WARNING"):
            self._start(d)
        self.assertFalse(d._hotkey.cancel_armed)

    def test_listener_gets_the_cancel_callback(self):
        d = daemon_service.STTDaemon(Config(sound_effects=False))
        d._recorder = mock.Mock()
        d._recorder.is_available.return_value = True
        engine = mock.Mock()
        with mock.patch.object(daemon_service, "build_engine", return_value=engine), \
                mock.patch.object(daemon_service, "AudioRecorder", return_value=d._recorder), \
                mock.patch.object(daemon_service, "HotkeyListener") as listener, \
                mock.patch.object(d, "_start_transcription_worker"):
            self.assertTrue(d._init_components())
        self.assertEqual(listener.call_args.kwargs["on_cancel"], d._on_recording_cancel)


class RecordingCommandTests(_Base):
    def _start(self, d):
        with mock.patch.object(daemon_service, "get_active_window", return_value=None):
            d._on_recording_start()

    def test_ac4_given_private_mode_off_when_recording_starts_then_plain_recording(self):
        d = self._daemon()
        self._start(d)
        self.assertEqual(self.sent, ["RECORDING"])

    def test_ac4_given_private_mode_on_when_recording_starts_then_private_flag_is_sent(self):
        (self.config_dir / history.PRIVATE_MODE_FILE).write_text('{"until": null}')
        d = self._daemon()
        self._start(d)
        self.assertEqual(self.sent, ["RECORDING PRIVATE"])

    def test_ac2_given_recording_when_main_loop_ticks_then_level_is_sent(self):
        d = self._daemon()
        self._start(d)
        d._overlay_push_level()
        self.assertEqual(self.sent[-1], "LEVEL 0.42")

    def test_ac2_given_idle_when_main_loop_ticks_then_no_level_is_sent(self):
        d = self._daemon()
        d._overlay_push_level()
        self.assertEqual(self.sent, [])


class DoneCommandTests(_Base):
    def _transcribe(self, d, result):
        d._engine = mock.Mock()
        d._engine.transcribe.return_value = "eins zwei drei"
        with mock.patch.object(daemon_service, "output_text", return_value=result), \
                self.assertLogs("claude_stt", "INFO"):
            d._process_transcription((np.full(32000, 0.1, dtype=np.float32), None, False))

    def test_ac6_given_inserted_then_done_carries_count_and_mode(self):
        d = self._daemon()
        self._transcribe(d, InsertResult(text="Eins zwei drei", mode="injection"))
        self.assertEqual(self.sent[-1], "DONE 3 injection")

    def test_ac6_given_clipboard_only_then_mode_is_clipboard(self):
        d = self._daemon()
        self._transcribe(d, InsertResult(text="Eins zwei drei", mode="clipboard"))
        self.assertEqual(self.sent[-1], "DONE 3 clipboard")

    def test_ac7_given_output_failed_then_a_hint_replaces_the_count(self):
        d = self._daemon()
        self._transcribe(d, None)
        self.assertEqual(self.sent[-1], "HINT Could not insert text")


class RecorderLevelTests(unittest.TestCase):
    def test_ac2_level_comes_from_the_last_recorded_chunk(self):
        rec = AudioRecorder(RecorderConfig())
        self.assertEqual(rec.current_level(), 0.0)
        rec._recorded_chunks.append(np.full((1024, 1), 0.0, dtype="float32"))
        self.assertEqual(rec.current_level(), 0.0)
        rec._recorded_chunks.append(np.full((1024, 1), 0.1, dtype="float32"))
        self.assertAlmostEqual(rec.current_level(), 0.8, places=2)  # -20 dB on a -60..-10 scale

    def test_level_needs_no_sounddevice(self):
        with mock.patch.object(recorder, "sd", None):
            self.assertEqual(AudioRecorder(RecorderConfig()).current_level(), 0.0)


if __name__ == "__main__":
    unittest.main()
