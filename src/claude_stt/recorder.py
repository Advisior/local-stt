"""Audio recording using sounddevice."""

import logging
import math
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Generator, Optional

import numpy as np

_SOUNDDEVICE_IMPORT_ERROR: Exception | None = None
try:
    import sounddevice as sd
except Exception as exc:
    sd = None
    _SOUNDDEVICE_IMPORT_ERROR = exc


@dataclass
class RecorderConfig:
    """Configuration for audio recording."""

    sample_rate: int = 16000
    channels: int = 1
    blocksize: int = 1024  # ~64ms at 16kHz
    dtype: str = "float32"
    queue_maxsize: int = 32
    max_recording_seconds: Optional[int] = None
    device: Optional[int | str] = None  # None = system default


@dataclass
class AudioChunk:
    """A chunk of recorded audio."""

    data: np.ndarray
    sample_rate: int
    timestamp: float


class AudioRecorder:
    """Records audio from the microphone.

    This class provides both blocking and streaming interfaces for recording.
    """

    def __init__(self, config: Optional[RecorderConfig] = None):
        """Initialize the recorder.

        Args:
            config: Recording configuration.
        """
        self.config = config or RecorderConfig()
        self._recording = False
        self._audio_queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream: Optional["sd.InputStream"] = None
        self._stream_warm: bool = False  # True once stream is pre-warmed
        self._recorded_chunks: Deque[np.ndarray] = deque()
        self._max_chunks = self._compute_max_chunks()
        self._lock = threading.Lock()
        self._logger = logging.getLogger(__name__)

    def _compute_max_chunks(self) -> Optional[int]:
        max_seconds = self.config.max_recording_seconds
        if not max_seconds:
            return None
        max_seconds = max(1, int(max_seconds))
        chunks = max_seconds * self.config.sample_rate / self.config.blocksize
        return max(1, int(math.ceil(chunks)))

    def is_available(self) -> bool:
        """Check if audio recording is available."""
        if sd is None:
            return False

        try:
            devices = sd.query_devices()
            return any(d.get("max_input_channels", 0) > 0 for d in devices)
        except Exception:
            return False

    def get_devices(self) -> list[dict]:
        """Get available input devices.

        Returns:
            List of device info dictionaries.
        """
        if sd is None:
            return []

        try:
            devices = sd.query_devices()
            return [
                {"name": d["name"], "index": i, "channels": d["max_input_channels"]}
                for i, d in enumerate(devices)
                if d["max_input_channels"] > 0
            ]
        except Exception:
            return []

    def _open_stream(self) -> bool:
        """Open the PortAudio input stream without starting a capture session."""
        if sd is None:
            return False
        if self._stream is not None:
            return True

        def callback(indata, frames, time_info, status):
            if status:
                self._logger.debug("Audio callback status: %s", status)
            try:
                self._audio_queue.put_nowait(indata.copy())
            except queue.Full:
                self._logger.debug("Audio queue full; dropping chunk")
            with self._lock:
                if self._recording:
                    self._recorded_chunks.append(indata.copy())

        try:
            self._stream = sd.InputStream(
                samplerate=self.config.sample_rate,
                channels=self.config.channels,
                dtype=self.config.dtype,
                blocksize=self.config.blocksize,
                device=self.config.device,
                callback=callback,
            )
            self._stream.start()
            return True
        except Exception:
            self._logger.exception("Failed to open audio stream")
            self._stream = None
            return False

    def prewarm(self) -> bool:
        """Open the audio stream early so the hardware buffer is ready.

        Call this once at daemon startup. After prewarm(), start() will not
        reopen the stream and the first recording will have no warmup delay.

        Returns:
            True if the stream was opened successfully.
        """
        if not self._open_stream():
            return False
        # Wait for the hardware buffer to fill; initial frames are zeros.
        time.sleep(0.3)
        self._stream_warm = True
        self._logger.debug("Audio stream pre-warmed")
        return True

    def start(self) -> bool:
        """Start recording audio.

        Returns:
            True if recording started successfully.
        """
        if sd is None:
            return False

        if self._recording:
            return True

        self._audio_queue = queue.Queue(maxsize=self.config.queue_maxsize)
        with self._lock:
            self._recorded_chunks = (
                deque(maxlen=self._max_chunks) if self._max_chunks else deque()
            )

        if self._stream_warm:
            # Stream already open and hardware buffer is full — just start capture.
            self._recording = True
            return True

        # Stream not pre-warmed: open it now and wait for hardware to settle.
        if not self._open_stream():
            return False
        time.sleep(0.3)
        with self._lock:
            self._recorded_chunks.clear()
        self._recording = True
        return True

    def stop(self) -> Optional[np.ndarray]:
        """Stop the current recording session and return captured audio.

        Does not close the underlying stream — keeps it warm for the next
        recording. Call close() to fully shut down the stream.

        Returns:
            Numpy array of all recorded audio, or None if no audio.
        """
        if not self._recording:
            return None

        self._recording = False

        if not self._stream_warm and self._stream is not None:
            # Stream was opened ad-hoc (no prewarm); close it now.
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                self._logger.debug("Failed to stop audio stream cleanly", exc_info=True)
            self._stream = None

        with self._lock:
            if not self._recorded_chunks:
                return None
            audio = np.concatenate(list(self._recorded_chunks))
            self._recorded_chunks = deque()
            return np.squeeze(audio)

    def close(self) -> None:
        """Close the audio stream (call on daemon shutdown)."""
        self._stream_warm = False
        self._recording = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                self._logger.debug("Failed to close audio stream", exc_info=True)
            self._stream = None

    def get_chunk(self, timeout: float = 0.1) -> Optional[np.ndarray]:
        """Get the next audio chunk from the recording stream.

        Args:
            timeout: How long to wait for a chunk.

        Returns:
            Audio chunk as numpy array, or None if timeout.
        """
        try:
            chunk = self._audio_queue.get(timeout=timeout)
            return np.squeeze(chunk)
        except queue.Empty:
            return None

    def iter_chunks(self) -> Generator[np.ndarray, None, None]:
        """Iterate over audio chunks while recording.

        Yields:
            Audio chunks as numpy arrays.
        """
        while self._recording:
            chunk = self.get_chunk()
            if chunk is not None:
                yield chunk

    @property
    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._recording

    def get_volume_level(self, chunk: np.ndarray) -> float:
        """Calculate volume level (0-1) for a chunk.

        Args:
            chunk: Audio chunk.

        Returns:
            Volume level from 0.0 to 1.0.
        """
        if chunk.size == 0:
            return 0.0

        # RMS volume
        rms = np.sqrt(np.mean(chunk**2))

        # Normalize to 0-1 range (assuming typical voice levels)
        # Adjust these thresholds based on testing
        min_db = -60
        max_db = -10
        db = 20 * np.log10(max(rms, 1e-10))
        normalized = (db - min_db) / (max_db - min_db)
        return max(0.0, min(1.0, normalized))


def get_sounddevice_import_error() -> Exception | None:
    """Return the sounddevice import error, if any."""
    return _SOUNDDEVICE_IMPORT_ERROR
