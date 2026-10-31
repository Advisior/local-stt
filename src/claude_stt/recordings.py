"""Local debug store of real dictations for ASR benchmarking (#50).

Off unless ``debug_keep_recordings`` is a positive integer. Each recording
that reached the engine is written as ``recordings/<stamp>.wav`` (16 kHz mono
16-bit PCM) plus a ``<stamp>.json`` sidecar, and only the newest N pairs are
kept. Nothing is written in private mode. Audio and sidecar hold personal
data, so the folder is 0700 and its files 0600.
"""

from __future__ import annotations

import json
import logging
import os
import re
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

from . import history
from .config import Config

RECORDINGS_DIR = "recordings"
# Only names this module writes take part in pruning, so samples or
# .ref.txt files the user drops into the folder are never deleted.
_STAMP_FORMAT = "%Y-%m-%d_%H-%M-%S-%f"
_STAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}-\d{6}(-\d+)?$")

_logger = logging.getLogger(__name__)


def model_name(config: Config) -> str:
    """The model setting the configured engine actually uses."""
    if config.engine == "moonshine":
        return config.moonshine_model
    if config.engine == "parakeet":
        return config.parakeet_model
    return config.whisper_model


def keep(
    audio: np.ndarray,
    config: Config,
    db: float,
    raw_text: str = "",
    text: str = "",
    private: bool = False,
) -> None:
    """Store the recording if the debug store is on and private mode is off.

    ``private`` marks a dictation the caller already knows is private; the
    current private mode state is checked as well.

    Never raises: a failed write logs the exception type only (no message,
    it could carry a path or text) and the dictation carries on (AC-5).
    """
    if config.debug_keep_recordings <= 0:
        return
    if private or history.private_mode_active():
        return
    try:
        save_recording(audio, config, db=db, raw_text=raw_text, text=text)
    except Exception as exc:
        _logger.warning("Could not store debug recording (%s)", type(exc).__name__)


def save_recording(
    audio: np.ndarray,
    config: Config,
    db: float,
    raw_text: str,
    text: str,
    now: Optional[datetime] = None,
) -> Path:
    """Write WAV and sidecar, then prune to ``debug_keep_recordings``. Returns the WAV path."""
    directory = Config.get_config_dir() / RECORDINGS_DIR
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)

    now = now or datetime.now()
    wav_path, wav_file = _create_unique(directory, now.strftime(_STAMP_FORMAT))
    json_path = wav_path.with_suffix(".json")
    try:
        with wav_file, wave.open(wav_file, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(config.sample_rate)
            wav.writeframes(_to_pcm16(audio))
        metadata = {
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S"),
            "duration_s": round(len(audio) / config.sample_rate, 2),
            "db": round(float(db), 1),
            "engine": config.engine,
            "model": model_name(config),
            "language": config.language,
            "initial_prompt": config.initial_prompt,
            "raw_text": raw_text,
            "text": text,
        }
        with _open_private(json_path) as handle:
            handle.write(json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"))
    except BaseException:
        for path in (wav_path, json_path):
            path.unlink(missing_ok=True)
        raise

    prune(directory, config.debug_keep_recordings)
    return wav_path


def prune(directory: Path, keep_count: int) -> None:
    """Delete the oldest stored WAV/JSON pairs until ``keep_count`` remain."""
    stems = sorted(
        {p.stem for p in directory.iterdir() if p.suffix in (".wav", ".json") and _STAMP_RE.match(p.stem)},
        key=_stem_sort_key,
    )
    for stem in stems[: max(len(stems) - keep_count, 0)]:
        for suffix in (".wav", ".json"):
            (directory / f"{stem}{suffix}").unlink(missing_ok=True)


def _stem_sort_key(stem: str) -> tuple[str, int]:
    base, _, suffix = stem[:26], stem[26:27], stem[27:]
    return base, int(suffix) if suffix else 0


def _create_unique(directory: Path, stamp: str):
    """Open ``<stamp>.wav`` exclusively, adding ``-1``, ``-2`` on a clash."""
    for attempt in range(100):
        stem = stamp if attempt == 0 else f"{stamp}-{attempt}"
        path = directory / f"{stem}.wav"
        try:
            return path, _open_private(path)
        except FileExistsError:
            continue
    raise FileExistsError("no free recording name")


def _open_private(path: Path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    os.chmod(path, 0o600)
    return os.fdopen(fd, "wb")


def _to_pcm16(audio: np.ndarray) -> bytes:
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    return (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
