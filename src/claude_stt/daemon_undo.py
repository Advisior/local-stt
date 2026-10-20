"""Undo-hotkey handling for STTDaemon (#45), kept apart to stay small."""

from __future__ import annotations

import platform

from .errors import HotkeyError
from .keyboard import undo_last_insert
from .sounds import play_sound
from .undo import UndoTracker


class UndoHotkeyMixin:
    """Needs config, _hotkey, _undo, _recording, _transcribing,
    _transcribe_queue, _logger and _overlay_send from STTDaemon."""

    def _setup_undo(self) -> None:
        """Register the optional undo hotkey (#45); failures leave recording intact."""
        hotkey = self.config.undo_hotkey
        if not hotkey or self._hotkey is None:
            return
        if platform.system() != "Darwin":
            self._logger.warning("undo_hotkey '%s' ignored: undo not supported on this platform", hotkey)
            return
        try:
            self._hotkey.add_binding("undo", hotkey, self._on_undo_hotkey)
        except HotkeyError as exc:
            self._logger.warning("Undo hotkey disabled: %s", exc)
            return
        self._undo = UndoTracker(self.config.undo_window_seconds, self.config.undo_max_chars)
        self._hotkey.on_other_key = self._undo.invalidate

    def _on_undo_hotkey(self) -> None:
        """Runs on the hotkey worker thread, never on the listener thread."""
        if self._undo is None:
            return
        busy = self._recording or self._transcribing or not self._transcribe_queue.empty()
        decision = self._undo.check(busy=busy)
        if decision.action == "ignore":
            self._logger.info("Undo ignored: recording or transcribing")
        elif decision.action == "refuse":
            self._logger.info("Undo refused: %s", decision.reason)
            self._overlay_send(f"HINT {decision.hint}")
            if self.config.sound_effects:
                play_sound("warning")
        elif not undo_last_insert(decision.count):
            self._logger.warning("Undo failed: could not send Backspaces")
        else:
            self._logger.info("Undo: removed %d characters", decision.count)
