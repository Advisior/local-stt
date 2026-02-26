"""MLX Whisper STT engine for Apple Silicon."""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

_mlx_whisper_available = False

try:
    import mlx_whisper as _mlx_whisper

    _mlx_whisper_available = True
except ImportError:
    _mlx_whisper = None


# Map short names to HuggingFace MLX model repos
_MODEL_MAP = {
    "tiny": "mlx-community/whisper-tiny",
    "base": "mlx-community/whisper-base",
    "small": "mlx-community/whisper-small",
    "medium": "mlx-community/whisper-medium",
    "large": "mlx-community/whisper-large-v3",
    "large-v3": "mlx-community/whisper-large-v3",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
}


class MLXWhisperEngine:
    """Whisper speech-to-text engine using MLX for Apple Silicon acceleration."""

    def __init__(
        self,
        model_name: str = "medium",
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
    ):
        self.model_name = model_name
        self.language = language
        self.initial_prompt = initial_prompt
        self._model_loaded = False
        self._hf_repo = _MODEL_MAP.get(model_name, model_name)
        self._logger = logging.getLogger(__name__)

    def is_available(self) -> bool:
        return _mlx_whisper_available

    def load_model(self) -> bool:
        if not self.is_available():
            return False
        if self._model_loaded:
            return True
        try:
            # MLX Whisper loads the model on first transcribe call,
            # but we trigger a warmup to download weights now
            self._logger.info("Loading MLX Whisper model: %s", self._hf_repo)
            _mlx_whisper.transcribe(
                np.zeros(16000, dtype=np.float32),
                path_or_hf_repo=self._hf_repo,
                verbose=False,
                language=self.language,
            )
            self._model_loaded = True
            return True
        except Exception:
            self._logger.exception("Failed to load MLX Whisper model")
            return False

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        if not self.load_model():
            return ""
        try:
            if audio.dtype != np.float32:
                audio = audio.astype(np.float32)

            kwargs = {
                "path_or_hf_repo": self._hf_repo,
                "verbose": False,
                # Prevent token repetition loops under CPU load.
                # compression_ratio_threshold aborts runs that produce
                # repetitive output (e.g. "Pol Pol Pol...").
                "compression_ratio_threshold": 2.4,
                # Filter near-silence segments to avoid wrong-language
                # hallucinations on borderline audio.
                "no_speech_threshold": 0.6,
                # Disable conditioning on previous segment to prevent
                # repetition cascades across segments.
                "condition_on_previous_text": False,
                "task": "transcribe",
                "temperature": 0,
                "word_timestamps": False,
            }
            if self.language:
                kwargs["language"] = self.language
            if self.initial_prompt:
                kwargs["initial_prompt"] = self.initial_prompt

            result = _mlx_whisper.transcribe(audio, **kwargs)
            text = result.get("text", "").strip()

            if self._has_excessive_repetition(text):
                self._logger.warning(
                    "Repetitive output detected (likely CPU load), discarding transcription"
                )
                return ""

            return text
        except Exception:
            self._logger.exception("MLX Whisper transcription failed")
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
