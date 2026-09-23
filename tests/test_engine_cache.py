import os
import tempfile
import unittest
from unittest import mock

from claude_stt import hf_cache
from claude_stt.engines import whisper
from claude_stt.engines.mlx_engine import MLXWhisperEngine
from claude_stt.engines.moonshine import MoonshineEngine
from claude_stt.engines.parakeet_engine import ParakeetEngine
from claude_stt.engines.whisper import WhisperEngine


class _FakeCache:
    """Stands in for hf_cache.is_cached and records every lookup."""

    def __init__(self, *cached: tuple[str, tuple[str, ...]]):
        self.cached = set(cached)
        self.lookups: list[tuple[str, tuple[str, ...]]] = []

    def __call__(self, repo_id, filenames, cache_dir=None):
        key = (repo_id, tuple(filenames))
        self.lookups.append(key)
        return key in self.cached


class MLXModelCacheTests(unittest.TestCase):
    def test_local_model_dir_counts_as_cached(self):
        fake = _FakeCache()
        with tempfile.TemporaryDirectory() as model_dir, mock.patch.object(
            hf_cache, "is_cached", fake
        ):
            self.assertTrue(MLXWhisperEngine(model_name=model_dir).is_model_cached())
        self.assertEqual(fake.lookups, [])

    def test_short_name_checks_config_and_weights(self):
        fake = _FakeCache(
            ("mlx-community/whisper-large-v3-turbo", ("config.json", "weights.safetensors"))
        )
        with mock.patch.object(hf_cache, "is_cached", fake):
            self.assertTrue(MLXWhisperEngine(model_name="large-v3-turbo").is_model_cached())

    def test_legacy_npz_weights_count_as_cached(self):
        fake = _FakeCache(("mlx-community/whisper-medium", ("config.json", "weights.npz")))
        with mock.patch.object(hf_cache, "is_cached", fake):
            self.assertTrue(MLXWhisperEngine(model_name="medium").is_model_cached())

    def test_not_cached(self):
        with mock.patch.object(hf_cache, "is_cached", _FakeCache()):
            self.assertFalse(MLXWhisperEngine(model_name="medium").is_model_cached())


class MoonshineModelCacheTests(unittest.TestCase):
    def test_checks_onnx_files_of_the_selected_size(self):
        folder = "onnx/merged/base/float"
        fake = _FakeCache(
            (
                "UsefulSensors/moonshine",
                (f"{folder}/encoder_model.onnx", f"{folder}/decoder_model_merged.onnx"),
            )
        )
        with mock.patch.object(hf_cache, "is_cached", fake):
            self.assertTrue(MoonshineEngine(model_name="moonshine/base").is_model_cached())
            self.assertFalse(MoonshineEngine(model_name="moonshine/tiny").is_model_cached())


class ParakeetModelCacheTests(unittest.TestCase):
    def test_checks_config_and_weights(self):
        fake = _FakeCache(
            ("mlx-community/parakeet-tdt-0.6b-v3", ("config.json", "model.safetensors"))
        )
        with mock.patch.object(hf_cache, "is_cached", fake):
            self.assertTrue(ParakeetEngine(model_name="tdt-0.6b-v3").is_model_cached())
            self.assertFalse(ParakeetEngine(model_name="tdt-1.1b").is_model_cached())


class FasterWhisperModelCacheTests(unittest.TestCase):
    def test_local_model_dir_counts_as_cached(self):
        with tempfile.TemporaryDirectory() as model_dir:
            self.assertTrue(WhisperEngine(model_name=model_dir).is_model_cached())

    def _probe_snapshot(self, files: list[str]) -> bool:
        with tempfile.TemporaryDirectory() as snapshot:
            for name in files:
                open(os.path.join(snapshot, name), "wb").close()
            probe = mock.Mock(return_value=snapshot)
            with mock.patch.object(whisper, "_download_model", probe):
                cached = WhisperEngine(model_name="small").is_model_cached()
            probe.assert_called_once_with("small", local_files_only=True)
            return cached

    def test_complete_snapshot_is_cached(self):
        self.assertTrue(
            self._probe_snapshot(["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"])
        )
        self.assertTrue(
            self._probe_snapshot(["config.json", "model.bin", "tokenizer.json", "vocabulary.json"])
        )

    def test_interrupted_download_is_not_cached(self):
        # Weights finished, companion files did not.
        self.assertFalse(self._probe_snapshot(["model.bin"]))
        self.assertFalse(self._probe_snapshot(["config.json", "model.bin", "tokenizer.json"]))
        self.assertFalse(self._probe_snapshot(["config.json", "tokenizer.json", "vocabulary.txt"]))

    def test_not_cached(self):
        probe = mock.Mock(side_effect=FileNotFoundError("not in cache"))
        with mock.patch.object(whisper, "_download_model", probe):
            self.assertFalse(WhisperEngine(model_name="small").is_model_cached())


if __name__ == "__main__":
    unittest.main()
