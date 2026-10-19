"""Undo the last dictation insert with Backspaces (#45).

Only the most recent insert is tracked. Undo is refused whenever the
Backspace count could remove anything other than exactly that text.
"""

from __future__ import annotations

import threading
import time
import unicodedata
from dataclasses import dataclass
from typing import Callable, Optional

from .keyboard import INSERT_MODES, InsertResult
from .window import frontmost_bundle_id

NOTHING_TO_UNDO = "Nothing to undo"
TOO_LONG_TO_UNDO = "Too long to undo"

_ZWJ = "‍"


@dataclass(frozen=True)
class UndoDecision:
    """Outcome of an undo request.

    action: "send" (send ``count`` Backspaces), "refuse" (show ``hint``,
    ``reason`` says why) or "ignore" (recording or transcribing).
    """

    action: str
    count: int = 0
    hint: str = ""
    reason: str = ""


@dataclass
class _Insert:
    text: str
    mode: str
    bundle_id: Optional[str]
    at: float
    token: int  # key-down generation before the insert started
    undone: bool = False


class UndoTracker:
    """Remembers the last dictation insert and decides whether undo is safe."""

    def __init__(
        self,
        window_seconds: float,
        max_chars: int,
        clock: Callable[[], float] = time.monotonic,
        frontmost_app: Callable[[], Optional[str]] = frontmost_bundle_id,
    ):
        self.window_seconds = window_seconds
        self.max_chars = max_chars
        self._clock = clock
        self._frontmost_app = frontmost_app
        self._lock = threading.Lock()
        self._generation = 0  # bumped by every user key-down
        self._last: Optional[_Insert] = None

    def invalidate(self) -> None:
        """A user key reached the focused app. Runs on the listener thread."""
        with self._lock:
            self._generation += 1

    def begin_insert(self) -> int:
        """Call right before output; keys typed during the paste then count."""
        with self._lock:
            return self._generation

    def record(self, result: InsertResult, token: int) -> None:
        """Remember what output_text delivered."""
        bundle_id = self._frontmost_app()
        with self._lock:
            self._last = _Insert(
                text=result.text,
                mode=result.mode,
                bundle_id=bundle_id,
                at=self._clock(),
                token=token,
            )

    def check(self, busy: bool) -> UndoDecision:
        """Decide what one press of the undo hotkey does.

        A "send" decision marks the insert as undone.
        """
        if busy:
            return UndoDecision("ignore")
        app = self._frontmost_app()
        with self._lock:
            last = self._last
            reason = self._refusal(last, app)
            if reason:
                return UndoDecision("refuse", hint=NOTHING_TO_UNDO, reason=reason)
            text = unicodedata.normalize("NFC", last.text)
            if "\n" in text or "\r" in text:
                return UndoDecision("refuse", hint=TOO_LONG_TO_UNDO, reason="text has a line break")
            if len(text) > self.max_chars:
                return UndoDecision(
                    "refuse",
                    hint=TOO_LONG_TO_UNDO,
                    reason=f"{len(text)} characters exceed undo_max_chars={self.max_chars}",
                )
            unsafe = _unsafe_char(text)
            if unsafe:
                return UndoDecision(
                    "refuse",
                    hint=NOTHING_TO_UNDO,
                    reason=f"one Backspace may not remove {unsafe}",
                )
            last.undone = True
            return UndoDecision("send", count=len(text))

    def _refusal(self, last: Optional[_Insert], app: Optional[str]) -> str:
        if last is None:
            return "no dictation inserted since start"
        if last.mode not in INSERT_MODES:
            return f"last dictation was only copied (mode {last.mode})"
        if last.undone:
            return "last dictation already undone"
        age = self._clock() - last.at
        if age > self.window_seconds:
            return f"last dictation is {age:.0f}s old (undo_window_seconds={self.window_seconds:g})"
        if app is None or app != last.bundle_id:
            return f"frontmost app changed ({last.bundle_id} -> {app})"
        if self._generation != last.token:
            return "a key was typed during or after the dictation"
        return ""


def _unsafe_char(text: str) -> str:
    """Describe the first character a single Backspace may not remove cleanly."""
    for ch in text:
        if ord(ch) > 0xFFFF:
            return f"non-BMP character U+{ord(ch):X}"
        if ch == _ZWJ:
            return "zero width joiner"
        if unicodedata.combining(ch):
            return f"combining mark U+{ord(ch):04X}"
    return ""
