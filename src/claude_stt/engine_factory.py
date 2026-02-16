"""STT engine construction and validation."""

from .config import Config
from .engines import STTEngine
from .engines.mlx_engine import MLXWhisperEngine
from .engines.moonshine import MoonshineEngine
from .engines.whisper import WhisperEngine
from .errors import EngineError


def build_engine(config: Config) -> STTEngine:
    """Create an engine instance for the configured engine."""
    if config.engine == "moonshine":
        return MoonshineEngine(model_name=config.moonshine_model)
    if config.engine == "whisper":
        return WhisperEngine(
            model_name=config.whisper_model,
            language=config.language,
            initial_prompt=config.initial_prompt,
        )
    if config.engine == "mlx":
        return MLXWhisperEngine(
            model_name=config.whisper_model,
            language=config.language,
            initial_prompt=config.initial_prompt,
        )
    raise EngineError(f"Unknown engine '{config.engine}'")
