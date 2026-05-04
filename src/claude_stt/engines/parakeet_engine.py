"""Parakeet TDT STT engine for Apple Silicon (NVIDIA Parakeet via MLX)."""

from __future__ import annotations

import logging

import numpy as np

_parakeet_available = False

try:
    import mlx.core as mx
    from parakeet_mlx import from_pretrained
    from parakeet_mlx.audio import get_logmel

    _parakeet_available = True
except ImportError:
    mx = None  # type: ignore[assignment]
    from_pretrained = None  # type: ignore[assignment]
    get_logmel = None  # type: ignore[assignment]


# Map short names to HuggingFace MLX-community model repos.
_MODEL_MAP = {
    "tdt-0.6b-v3": "mlx-community/parakeet-tdt-0.6b-v3",
    "tdt-0.6b-v2": "mlx-community/parakeet-tdt-0.6b-v2",
    "tdt-1.1b": "mlx-community/parakeet-tdt-1.1b",
}


class ParakeetEngine:
    """NVIDIA Parakeet TDT engine using MLX on Apple Silicon.

    Parakeet is multilingual (25 European languages including German) and
    typically delivers sub-100ms latency. Unlike Whisper it does not accept
    a language hint or initial prompt; the model auto-detects from audio.
    """

    def __init__(
        self,
        model_name: str = "tdt-0.6b-v3",
    ):
        self.model_name = model_name
        self._hf_repo = _MODEL_MAP.get(model_name, model_name)
        self._model = None
        self._logger = logging.getLogger(__name__)

    def is_available(self) -> bool:
        return _parakeet_available

    def load_model(self) -> bool:
        if not self.is_available():
            return False
        if self._model is not None:
            return True
        try:
            self._logger.info("Loading Parakeet model: %s", self._hf_repo)
            self._model = from_pretrained(self._hf_repo)
            # Force eager weight load so the first transcribe() call is
            # responsive instead of blocking 30+s on lazy materialization.
            import numpy as _np

            warmup = mx.array(_np.zeros(16000, dtype=_np.float32))
            mel = get_logmel(warmup, self._model.preprocessor_config)
            self._model.generate(mel)
            self._logger.info("Parakeet model ready")
            return True
        except Exception:
            self._logger.exception("Failed to load Parakeet model")
            return False

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        if not self.load_model():
            return ""
        try:
            if audio.dtype != np.float32:
                audio = audio.astype(np.float32)

            expected_sr = self._model.preprocessor_config.sample_rate
            if sample_rate != expected_sr:
                self._logger.warning(
                    "Sample rate mismatch (got %d, model expects %d); "
                    "transcription quality may degrade",
                    sample_rate,
                    expected_sr,
                )

            audio_mx = mx.array(audio)
            mel = get_logmel(audio_mx, self._model.preprocessor_config)
            results = self._model.generate(mel)
            if not results:
                return ""
            text = results[0].text.strip()

            if self._has_excessive_repetition(text):
                self._logger.warning(
                    "Repetitive output detected, discarding transcription"
                )
                return ""

            return text
        except Exception:
            self._logger.exception("Parakeet transcription failed")
            return ""

    @staticmethod
    def _has_excessive_repetition(text: str, threshold: int = 5) -> bool:
        """Return True if more than `threshold` consecutive identical words."""
        words = text.split()
        if len(words) < threshold:
            return False
        for i in range(len(words) - threshold + 1):
            if len(set(words[i : i + threshold])) == 1:
                return True
        return False
