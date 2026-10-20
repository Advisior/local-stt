import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from claude_stt import daemon_service, history
from claude_stt.config import Config

SECRET = "Kontonummer siebzehn geheim"


class _FakeEngine:
    def __init__(self, text: str):
        self.text = text

    def transcribe(self, audio, sample_rate):
        return self.text


class ProcessTranscriptionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config_dir = Path(self._tmp.name)
        self._env = mock.patch.dict(os.environ, {"CLAUDE_STT_CONFIG_DIR": str(self.config_dir)})
        self._env.start()
        self.daemon = daemon_service.STTDaemon(Config(sound_effects=False))
        self.daemon._engine = _FakeEngine(SECRET)
        self.daemon._overlay_send = lambda command: None
        self.output = mock.patch.object(daemon_service, "output_text", return_value=True)
        self.output_mock = self.output.start()

    def tearDown(self):
        self.output.stop()
        self._env.stop()
        self._tmp.cleanup()

    def dictate(self):
        audio = np.full(16000 * 2, 0.1, dtype=np.float32)
        with self.assertLogs("claude_stt", level="DEBUG") as logs:
            self.daemon._process_transcription((audio, None))
        return logs.output

    def history_texts(self):
        path = self.config_dir / history.HISTORY_FILE
        if not path.exists():
            return []
        return [json.loads(line)["text"] for line in path.read_text().splitlines() if line.strip()]

    def set_private(self, raw: str):
        (self.config_dir / history.PRIVATE_MODE_FILE).write_text(raw)

    def test_ac14_given_private_mode_off_when_dictating_then_history_gets_entry(self):
        self.dictate()
        self.assertEqual(self.history_texts(), [SECRET])

    def test_ac7_given_private_mode_on_when_dictating_then_history_is_not_written(self):
        self.set_private('{"until": null}')
        self.dictate()
        self.assertEqual(self.history_texts(), [])

    def test_ac15_given_private_mode_on_when_dictating_then_text_is_still_output_privately(self):
        self.set_private('{"until": null}')
        self.dictate()
        self.output_mock.assert_called_once()
        self.assertEqual(self.output_mock.call_args.args[0], SECRET)
        self.assertTrue(self.output_mock.call_args.kwargs["private"])

    def test_ac10_given_private_mode_elapsed_when_dictating_then_history_is_written_again(self):
        self.set_private('{"until": "2000-01-01T00:00:00Z"}')
        self.dictate()
        self.assertEqual(self.history_texts(), [SECRET])
        self.assertFalse(self.output_mock.call_args.kwargs["private"])

    def test_ac12_given_malformed_private_state_when_dictating_then_history_is_not_written(self):
        self.set_private("{broken")
        logs = self.dictate()
        self.assertEqual(self.history_texts(), [])
        self.assertTrue(any("WARNING" in line for line in logs))

    def test_ac13_given_any_mode_when_dictating_then_log_has_word_count_and_no_text(self):
        for private_state in (None, '{"until": null}'):
            with self.subTest(private=private_state is not None):
                if private_state:
                    self.set_private(private_state)
                logs = self.dictate()
                joined = "\n".join(logs)
                self.assertIn("Transcribed 3 words", joined)
                for word in SECRET.split():
                    self.assertNotIn(word, joined)


if __name__ == "__main__":
    unittest.main()
