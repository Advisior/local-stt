"""Input stream recovery for STTDaemon (#44), kept apart to stay small."""

from __future__ import annotations

import logging
import queue
import time
from typing import Optional

from .audio_devices import default_input_device_id
from .sounds import play_sound

NO_INPUT_HINT = "HINT No microphone input. Check the input device."
DEFAULT_INPUT_POLL_SECONDS = 2.0

_logger = logging.getLogger(__name__)


class AudioRecoveryMixin:
    """Needs config, _recorder, _recording, _lock, _transcribe_queue,
    _restore_system_audio and _overlay_send from STTDaemon."""

    _default_input_id: Optional[int] = None
    _next_default_input_check: float = 0.0

    def _report_no_input(self) -> None:
        """AC-3: tell the user that the recording got no microphone input."""
        device = self._recorder.device_name() if self._recorder else "unknown device"
        _logger.warning("No microphone input from %s; recording ended", device)
        self._overlay_send(NO_INPUT_HINT)
        if self.config.sound_effects:
            play_sound("error")

    def _check_audio_stream(self) -> None:
        """Main-loop watchdog while recording (AC-2, AC-3)."""
        if not self._recording or not self._recorder:
            return
        with self._lock:
            if not self._recording or self._recorder.ensure_alive():
                return
            self._recording = False
            if self.config.mute_on_record:
                self._restore_system_audio()
            audio = self._recorder.stop()
            window_info = self._original_window
            self._report_no_input()
        # Audio captured before the drop still gets transcribed.
        if audio is not None and len(audio) > 0:
            try:
                self._transcribe_queue.put_nowait((audio, window_info))
            except queue.Full:
                _logger.warning("Dropping transcription; queue is full")

    def _reopen_after_empty_recording(self) -> None:
        """AC-4: rebind the stream so the next recording uses the current input."""
        with self._lock:
            if self._recording or not self._recorder:
                return
            self._recorder.reopen()

    def _check_default_input(self) -> None:
        """AC-5, AC-6: follow macOS default-input changes while idle."""
        if self.config.audio_device is not None or not self._recorder:
            return
        now = time.monotonic()
        if now < self._next_default_input_check:
            return
        self._next_default_input_check = now + DEFAULT_INPUT_POLL_SECONDS
        if self._recording:
            return
        device_id = default_input_device_id()
        if device_id is None:
            return
        previous, self._default_input_id = self._default_input_id, device_id
        if previous is None or previous == device_id:
            return
        _logger.info("Default input changed (CoreAudio id %d -> %d); reopening stream", previous, device_id)
        with self._lock:
            if self._recording:
                self._default_input_id = previous  # retry once the recording ends
                return
            self._recorder.reopen()
