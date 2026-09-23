import tempfile
import unittest
from pathlib import Path

from claude_stt import hf_cache

COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _make_cached_repo(cache_dir: str, repo_id: str, files: list[str]) -> None:
    """Lay out files the way huggingface_hub stores a downloaded snapshot."""
    repo_dir = Path(cache_dir) / f"models--{repo_id.replace('/', '--')}"
    (repo_dir / "refs").mkdir(parents=True)
    (repo_dir / "refs" / "main").write_text(COMMIT)
    for name in files:
        path = repo_dir / "snapshots" / COMMIT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"weights")


class IsCachedTests(unittest.TestCase):
    def test_true_when_every_file_is_cached(self):
        with tempfile.TemporaryDirectory() as cache:
            files = ["config.json", "onnx/merged/base/float/encoder_model.onnx"]
            _make_cached_repo(cache, "org/model", files)
            self.assertTrue(hf_cache.is_cached("org/model", files, cache_dir=cache))

    def test_false_when_a_file_is_missing(self):
        # An interrupted download leaves the config without the weights.
        with tempfile.TemporaryDirectory() as cache:
            _make_cached_repo(cache, "org/model", ["config.json"])
            self.assertFalse(
                hf_cache.is_cached(
                    "org/model", ["config.json", "weights.safetensors"], cache_dir=cache
                )
            )

    def test_false_when_repo_was_never_downloaded(self):
        with tempfile.TemporaryDirectory() as cache:
            self.assertFalse(hf_cache.is_cached("org/model", ["config.json"], cache_dir=cache))

    def test_false_for_a_path_that_is_not_a_repo_id(self):
        with tempfile.TemporaryDirectory() as cache:
            self.assertFalse(
                hf_cache.is_cached("/no/such/model/dir", ["config.json"], cache_dir=cache)
            )


if __name__ == "__main__":
    unittest.main()
