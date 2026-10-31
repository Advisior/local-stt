"""Debug recording store (#50, AC-1 to AC-7, AC-13, AC-14)."""

import json
import logging
import os
import stat
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

import numpy as np

from claude_stt import daemon_service, history, recordings
from claude_stt.config import Config
from claude_stt.keyboard import InsertResult

SECRET = "Kontonummer siebzehn geheim"
POSIX = os.name != "nt"


class _FakeEngine:
    def __init__(self, text: str):
        self.text = text

    def transcribe(self, audio, sample_rate):
        return self.text


class _DaemonCase(unittest.TestCase):
    keep = 3

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config_dir = Path(self._tmp.name)
        self._env = mock.patch.dict(os.environ, {"LOCAL_STT_CONFIG_DIR": str(self.config_dir)})
        self._env.start()
        config = Config(
            sound_effects=False,
            engine="mlx",
            whisper_model="large-v3-turbo",
            language="de",
            initial_prompt="Fachbegriffe",
            debug_keep_recordings=self.keep,
        )
        self.daemon = daemon_service.STTDaemon(config)
        self.daemon._engine = _FakeEngine(SECRET)
        self.daemon._overlay_send = lambda command: None
        self.output = mock.patch.object(
            daemon_service, "output_text", return_value=InsertResult(text=SECRET + ". ", mode="injection")
        )
        self.output_mock = self.output.start()

    def tearDown(self):
        self.output.stop()
        self._env.stop()
        self._tmp.cleanup()

    @property
    def rec_dir(self) -> Path:
        return self.config_dir / recordings.RECORDINGS_DIR

    def dictate(self, seconds: float = 2.0, level: float = 0.1, recorded_private: bool = False):
        audio = np.full(int(16000 * seconds), level, dtype=np.float32)
        with self.assertLogs("claude_stt", level="DEBUG") as logs:
            self.daemon._process_transcription((audio, None, recorded_private))
        return logs

    def stems(self):
        if not self.rec_dir.exists():
            return []
        return sorted(p.stem for p in self.rec_dir.glob("*.wav"))

    def sidecar(self, stem):
        return json.loads((self.rec_dir / f"{stem}.json").read_text(encoding="utf-8"))


class RecordingStoreTests(_DaemonCase):
    def test_ac1_given_store_on_when_dictating_then_wav_and_sidecar_are_written(self):
        self.daemon.config.corrections = {"geheim": "GEHEIM"}
        with mock.patch.object(self.daemon.config, "reload_corrections"):
            self.dictate(seconds=1.5)

        [stem] = self.stems()
        with wave.open(str(self.rec_dir / f"{stem}.wav"), "rb") as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertEqual(wav.getframerate(), 16000)
            self.assertEqual(wav.getnframes(), 24000)
        meta = self.sidecar(stem)
        self.assertEqual(
            set(meta),
            {"timestamp", "duration_s", "db", "engine", "model", "language",
             "initial_prompt", "raw_text", "text"},
        )
        self.assertEqual(meta["duration_s"], 1.5)
        self.assertEqual(meta["db"], -20.0)
        self.assertEqual(meta["engine"], "mlx")
        self.assertEqual(meta["model"], "large-v3-turbo")
        self.assertEqual(meta["language"], "de")
        self.assertEqual(meta["initial_prompt"], "Fachbegriffe")
        self.assertEqual(meta["raw_text"], SECRET)
        self.assertEqual(meta["text"], "Kontonummer siebzehn GEHEIM")

    def test_ac1_given_moonshine_engine_then_sidecar_names_the_moonshine_model(self):
        self.daemon.config.engine = "moonshine"
        self.dictate()
        self.assertEqual(self.sidecar(self.stems()[0])["model"], "moonshine/base")

    def test_ac1_given_too_quiet_recording_then_nothing_is_stored(self):
        self.dictate(seconds=2.0, level=0.0001)
        self.assertEqual(self.stems(), [])

    def test_ac2_given_more_than_n_recordings_then_oldest_pairs_are_deleted(self):
        for _ in range(5):
            self.dictate()
        stems = self.stems()
        self.assertEqual(len(stems), 3)
        self.assertEqual(sorted(p.stem for p in self.rec_dir.glob("*.json")), stems)

    def test_ac2_given_foreign_files_in_folder_then_pruning_leaves_them_alone(self):
        self.rec_dir.mkdir(parents=True)
        (self.rec_dir / "0000-sample.wav").write_bytes(b"x")
        (self.rec_dir / "0000-sample.ref.txt").write_text("ref")
        for _ in range(4):
            self.dictate()
        self.assertTrue((self.rec_dir / "0000-sample.wav").exists())
        self.assertTrue((self.rec_dir / "0000-sample.ref.txt").exists())
        self.assertEqual(len([s for s in self.stems() if s != "0000-sample"]), 3)

    def test_ac3_given_private_mode_on_when_dictating_then_nothing_is_stored(self):
        (self.config_dir / history.PRIVATE_MODE_FILE).write_text('{"until": null}')
        self.dictate()
        self.daemon._engine = _FakeEngine("")
        self.dictate()
        self.assertFalse(self.rec_dir.exists())

    def test_ac3_given_private_mode_ends_while_inserting_then_nothing_is_stored(self):
        private_file = self.config_dir / history.PRIVATE_MODE_FILE
        private_file.write_text('{"until": null}')

        def insert_then_end_private(*args, **kwargs):
            private_file.unlink()
            return InsertResult(text=SECRET + ". ", mode="injection")

        self.output_mock.side_effect = insert_then_end_private
        self.dictate()
        self.assertFalse(self.rec_dir.exists())

    def test_ac3_given_recorded_in_private_mode_when_it_ends_before_transcribing_then_nothing_is_stored(self):
        self.dictate(recorded_private=True)
        self.daemon._engine = _FakeEngine("")
        self.dictate(recorded_private=True)
        self.daemon._engine = mock.Mock(transcribe=mock.Mock(side_effect=RuntimeError("engine")))
        self.dictate(recorded_private=True)
        self.assertFalse(self.rec_dir.exists())
        self.assertFalse((self.config_dir / history.HISTORY_FILE).exists())

    def test_ac3_given_private_mode_on_when_recording_stops_then_the_queue_item_carries_it(self):
        (self.config_dir / history.PRIVATE_MODE_FILE).write_text('{"until": null}')
        recorder = mock.Mock(stop=mock.Mock(return_value=np.full(32000, 0.1, dtype=np.float32)))
        self.daemon._recorder = recorder
        self.daemon._recording = True
        self.daemon._record_start_time = 0.0
        self.daemon._on_recording_stop()
        self.assertTrue(self.daemon._transcribe_queue.get_nowait()[2])

    def test_ac5_given_write_fails_then_warning_without_text_and_dictation_continues(self):
        with mock.patch.object(recordings.wave, "open", side_effect=OSError(28, "No space left " + SECRET)):
            logs = self.dictate()
        formatted = "\n".join(logging.Formatter().format(r) for r in logs.records)
        self.assertIn("WARNING", "\n".join(logs.output))
        self.assertIn("OSError", formatted)
        for word in SECRET.split():
            self.assertNotIn(word, formatted)
        self.output_mock.assert_called_once()
        self.assertEqual(json.loads((self.config_dir / history.HISTORY_FILE).read_text())["text"], SECRET)
        self.assertEqual(list(self.rec_dir.glob("*")), [])

    @unittest.skipUnless(POSIX, "POSIX file modes")
    def test_ac6_given_store_on_then_dir_is_0700_and_files_are_0600(self):
        self.dictate()
        self.assertEqual(stat.S_IMODE(self.rec_dir.stat().st_mode), 0o700)
        for path in self.rec_dir.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path.name)

    @unittest.skipUnless(POSIX, "POSIX file modes")
    def test_ac6_given_existing_open_dir_then_it_is_tightened_to_0700(self):
        self.rec_dir.mkdir(mode=0o755)
        os.chmod(self.rec_dir, 0o755)
        self.dictate()
        self.assertEqual(stat.S_IMODE(self.rec_dir.stat().st_mode), 0o700)

    def test_ac7_given_engine_returns_no_speech_then_recording_is_stored_with_empty_texts(self):
        self.daemon._engine = _FakeEngine("   ")
        self.dictate()
        [stem] = self.stems()
        meta = self.sidecar(stem)
        self.assertEqual((meta["raw_text"], meta["text"]), ("", ""))
        self.output_mock.assert_not_called()

    def test_ac7_given_engine_raises_then_recording_is_stored_with_empty_texts(self):
        self.daemon._engine = mock.Mock()
        self.daemon._engine.transcribe.side_effect = RuntimeError("boom")
        self.dictate()
        meta = self.sidecar(self.stems()[0])
        self.assertEqual((meta["raw_text"], meta["text"]), ("", ""))

    def test_ac14_given_store_on_then_log_has_no_text_and_history_is_unchanged(self):
        logs = self.dictate()
        joined = "\n".join(logs.output)
        for word in SECRET.split():
            self.assertNotIn(word, joined)
        lines = (self.config_dir / history.HISTORY_FILE).read_text().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(
            set(json.loads(lines[0])), {"timestamp", "text", "duration_s", "db", "words"}
        )


class RecordingStoreOffTests(_DaemonCase):
    keep = 0

    def test_ac13_given_setting_off_when_dictating_then_no_audio_is_written_anywhere(self):
        before = set(self.config_dir.rglob("*"))
        with mock.patch.object(recordings.wave, "open") as wave_open:
            self.dictate()
            self.daemon._engine = _FakeEngine("")
            self.dictate()
        wave_open.assert_not_called()
        created = {p.name for p in set(self.config_dir.rglob("*")) - before}
        self.assertEqual(created, {history.HISTORY_FILE, history.LOCK_FILE})

    def test_ac13_given_setting_off_then_private_state_is_not_read_for_recordings(self):
        with mock.patch.object(recordings.history, "private_mode_active") as private:
            recordings.keep(np.zeros(16000, dtype=np.float32), self.daemon.config, db=-20.0)
        private.assert_not_called()


class ConfigSettingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config_dir = Path(self._tmp.name)
        self._env = mock.patch.dict(os.environ, {"LOCAL_STT_CONFIG_DIR": str(self.config_dir)})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def load_with(self, line: str):
        (self.config_dir / "config.toml").write_text(f"[claude-stt]\n{line}\n")
        return Config.load()

    def test_ac4_given_setting_missing_then_store_is_off_without_warning(self):
        (self.config_dir / "config.toml").write_text('[claude-stt]\nhotkey = "f1"\n')
        with self.assertNoLogs("claude_stt.config", level="WARNING"):
            config = Config.load()
        self.assertEqual(config.debug_keep_recordings, 0)

    def test_ac4_given_zero_then_store_is_off_without_warning(self):
        with self.assertNoLogs("claude_stt.config", level="WARNING"):
            config = self.load_with("debug_keep_recordings = 0")
        self.assertEqual(config.debug_keep_recordings, 0)

    def test_ac4_given_positive_integer_then_it_is_kept(self):
        self.assertEqual(self.load_with("debug_keep_recordings = 20").debug_keep_recordings, 20)

    def test_ac4_given_invalid_value_then_store_is_off_with_one_warning_at_startup(self):
        for raw in ("-1", '"20"', "2.5", "true", "[1]"):
            with self.subTest(raw=raw):
                with self.assertLogs("claude_stt", level="WARNING") as logs:
                    config = self.load_with(f"debug_keep_recordings = {raw}")
                    daemon_service.STTDaemon(config)
                warnings = [line for line in logs.output if "debug_keep_recordings" in line]
                self.assertEqual(len(warnings), 1, logs.output)
                self.assertEqual(config.debug_keep_recordings, 0)

    def test_ac4_given_positive_value_then_save_round_trips_it(self):
        Config(debug_keep_recordings=7).save()
        self.assertEqual(Config.load().debug_keep_recordings, 7)

    def test_ac13_given_default_then_save_does_not_write_the_setting(self):
        Config().save()
        self.assertNotIn("debug_keep_recordings", (self.config_dir / "config.toml").read_text())


if __name__ == "__main__":
    unittest.main()
