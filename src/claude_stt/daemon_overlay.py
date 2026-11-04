"""Overlay subprocess and Esc cancel for STTDaemon (#60), kept apart to stay small."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional

from . import history


class OverlayMixin:
    """Needs config, _recorder, _hotkey, _lock, _logger, _restore_system_audio
    from STTDaemon. Owns the overlay subprocess and the ``_recording`` flag,
    which keeps the listener's Esc cancel armed exactly while recording."""

    _overlay_proc: Optional[subprocess.Popen] = None
    _recording_flag: bool = False

    @property
    def _recording(self) -> bool:
        return self._recording_flag

    @_recording.setter
    def _recording(self, value: bool) -> None:
        self._recording_flag = value
        hotkey = getattr(self, "_hotkey", None)
        if hotkey is not None:
            hotkey.cancel_armed = value

    def _start_overlay(self) -> None:
        """Start the overlay indicator subprocess."""
        try:
            overlay_module = os.path.join(os.path.dirname(__file__), "overlay.py")
            self._overlay_proc = subprocess.Popen(
                [sys.executable, overlay_module],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._logger.info("Overlay indicator started (PID %d)", self._overlay_proc.pid)
        except Exception:
            self._logger.debug("Overlay indicator not available", exc_info=True)
            self._overlay_proc = None

    def _overlay_send(self, command: str) -> None:
        """Send a command to the overlay subprocess."""
        if self._overlay_proc and self._overlay_proc.poll() is None:
            try:
                self._overlay_proc.stdin.write((command + "\n").encode())
                self._overlay_proc.stdin.flush()
            except (BrokenPipeError, OSError):
                self._overlay_proc = None

    def _stop_overlay(self) -> None:
        """Stop the overlay subprocess."""
        if self._overlay_proc and self._overlay_proc.poll() is None:
            self._overlay_send("QUIT")
            try:
                self._overlay_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._overlay_proc.kill()
            self._overlay_proc = None

    def _overlay_recording_command(self) -> str:
        """RECORDING, with PRIVATE when private mode is on (AC-4)."""
        return "RECORDING PRIVATE" if history.private_mode_active() else "RECORDING"

    def _overlay_push_level(self) -> None:
        """Main-loop tick: one microphone level sample for the meter (AC-2)."""
        if not self._recording or not self._recorder:
            return
        self._overlay_send(f"LEVEL {self._recorder.current_level():.2f}")

    def _on_recording_cancel(self) -> None:
        """Esc while recording (AC-8): drop the audio, no transcription, no history."""
        with self._lock:
            if not self._recording:
                return
            self._recording = False
            if self.config.mute_on_record:
                self._restore_system_audio()
            if self._recorder:
                self._recorder.stop()
        self._logger.info("Recording cancelled")
        self._overlay_send("CANCEL")
