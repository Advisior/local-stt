import unittest

from claude_stt.config import Config
from claude_stt.engine_factory import build_engine
from claude_stt.engines.parakeet_engine import ParakeetEngine
from claude_stt.engines.whisper import WhisperEngine
from claude_stt.errors import EngineError


class EngineFactoryTests(unittest.TestCase):
    def test_unknown_engine_rejected(self):
        config = Config(engine="unknown").validate()
        # validate defaults to moonshine, so force raw config
        config.engine = "unknown"
        with self.assertRaises(EngineError):
            build_engine(config)

    def test_whisper_engine_constructed(self):
        config = Config(engine="whisper")
        engine = build_engine(config)
        self.assertIsInstance(engine, WhisperEngine)

    def test_parakeet_engine_constructed(self):
        config = Config(engine="parakeet")
        engine = build_engine(config)
        self.assertIsInstance(engine, ParakeetEngine)
        self.assertEqual(engine.model_name, "tdt-0.6b-v3")


if __name__ == "__main__":
    unittest.main()
