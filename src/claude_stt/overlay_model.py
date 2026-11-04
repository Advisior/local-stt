"""State, text and layout logic for the recording HUD (#60).

Kept free of AppKit so it runs and is tested on every platform; overlay.py
only draws what this module decides.

Overlay protocol (one command per stdin line):
  RECORDING [PRIVATE]   start the recording HUD, optionally in private mode
  LEVEL <0..1>          push one microphone level sample for the meter
  TRANSCRIBING          switch to "Transcribing…"
  DONE <n> [mode]       "Inserted n words" ("Copied" for mode "clipboard")
  HINT <text>           short notice with a warning symbol
  CANCEL                hide immediately
  QUIT                  exit the overlay process
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Optional, Sequence

HIDDEN = "hidden"
RECORDING = "recording"
TRANSCRIBING = "transcribing"
DONE = "done"
HINT = "hint"

COMMANDS = ("RECORDING", "LEVEL", "TRANSCRIBING", "DONE", "HINT", "CANCEL", "QUIT")
METER_BARS = 14
TRANSCRIBING_TEXT = "Transcribing…"
LISTENING_TEXT = "Listening"
ESC_TEXT = "esc"


@dataclass(frozen=True)
class Command:
    name: str
    args: tuple = ()


@dataclass(frozen=True)
class HudState:
    kind: str = HIDDEN
    private: bool = False
    started_at: float = 0.0
    text: str = ""
    levels: tuple = field(default_factory=tuple)


@dataclass(frozen=True)
class Item:
    """One element of the capsule, drawn left to right by overlay.py."""

    kind: str  # dot, symbol, spinner, meter, text, time, key
    label: str  # VoiceOver label
    text: str = ""
    symbol: str = ""
    secondary: bool = False


def format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60}:{total % 60:02d}"


def spoken_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    parts = []
    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if secs or not minutes:
        parts.append(f"{secs} second{'s' if secs != 1 else ''}")
    return " ".join(parts)


def done_text(count: int, mode: str) -> str:
    verb = "Copied" if mode == "clipboard" else "Inserted"
    return f"{verb} {count} word{'' if count == 1 else 's'}"


def parse_command(line: str) -> Optional[Command]:
    """Split a protocol line; HINT keeps its whole text as one argument."""
    line = line.strip()
    if not line:
        return None
    name, _, rest = line.partition(" ")
    if name not in COMMANDS:
        return None
    if name == "HINT":
        return Command(name, (rest,) if rest else ())
    return Command(name, tuple(rest.split()))


def _parse_level(raw: str) -> Optional[float]:
    try:
        value = float(raw)
    except ValueError:
        return None
    if math.isnan(value):
        return None
    return min(1.0, max(0.0, value))


def _parse_count(raw: str) -> int:
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def apply(state: HudState, command: Command, now: float) -> HudState:
    """The next HUD state after a command. QUIT is handled by the caller."""
    name, args = command.name, command.args
    if name == "RECORDING":
        return HudState(kind=RECORDING, private="PRIVATE" in args, started_at=now)
    if name == "LEVEL":
        if state.kind != RECORDING or not args:
            return state
        level = _parse_level(args[0])
        if level is None:
            return state
        return replace(state, levels=(state.levels + (level,))[-METER_BARS:])
    if name == "TRANSCRIBING":
        return replace(state, kind=TRANSCRIBING, text=TRANSCRIBING_TEXT, levels=())
    if name == "DONE":
        count = _parse_count(args[0]) if args else 0
        mode = args[1] if len(args) > 1 else ""
        return HudState(kind=DONE, text=done_text(count, mode))
    if name == "HINT":
        return HudState(kind=HINT, text=args[0] if args else "")
    if name == "CANCEL":
        return HudState()
    return state


def hud_items(state: HudState, reduce_motion: bool, now: float) -> list[Item]:
    """The capsule's content, left to right, for one state."""
    kind = state.kind
    if kind == RECORDING:
        elapsed = now - state.started_at
        items = [Item("dot", "Recording")]
        if state.private:
            items.append(Item("symbol", "Private mode", symbol="eye.slash", secondary=True))
        if reduce_motion:
            items.append(Item("symbol", "Microphone", symbol="mic.fill", secondary=True))
            items.append(Item("text", LISTENING_TEXT, text=LISTENING_TEXT))
        else:
            items.append(Item("meter", "Audio level"))
        items.append(Item("time", spoken_duration(elapsed), text=format_elapsed(elapsed), secondary=True))
        items.append(Item("key", "Press Escape to cancel", text=ESC_TEXT, secondary=True))
        return items
    if kind == TRANSCRIBING:
        lead = (
            Item("symbol", "Transcribing", symbol="ellipsis.circle", secondary=True)
            if reduce_motion
            else Item("spinner", "Transcribing")
        )
        return [lead, Item("text", state.text, text=state.text)]
    if kind == DONE:
        return [
            Item("symbol", "Done", symbol="checkmark.circle.fill"),
            Item("text", state.text, text=state.text),
        ]
    if kind == HINT:
        return [
            Item("symbol", "Notice", symbol="exclamationmark.triangle.fill"),
            Item("text", state.text, text=state.text),
        ]
    return []


def announcement(state: HudState) -> Optional[str]:
    """What VoiceOver announces when the HUD enters a state."""
    if state.kind == RECORDING:
        return "Recording, private mode" if state.private else "Recording"
    if state.kind == TRANSCRIBING:
        return "Transcribing"
    if state.kind in (DONE, HINT):
        return state.text or None
    return None


def layout(
    widths: Sequence[float], padding: float, spacing: float, max_width: Optional[float] = None
) -> tuple[list[float], float]:
    """X origins of the items and the capsule width that fits them."""
    origins = []
    x = padding
    for i, width in enumerate(widths):
        if i:
            x += spacing
        origins.append(x)
        x += width
    total = x + padding
    if max_width is not None:
        total = min(total, max_width)
    return origins, total


def capsule_origin(visible_frame, width: float, height: float, margin: float) -> tuple[float, float]:
    """Bottom center of a screen's visible frame (x, y, w, h), above the Dock."""
    x, y, w, _h = visible_frame
    return x + (w - width) / 2, y + margin


def bar_heights(levels: Sequence[float], bars: int, min_h: float, max_h: float) -> list[float]:
    """Meter bar heights, newest level on the right, silence padded on the left."""
    recent = list(levels)[-bars:]
    padded = [0.0] * (bars - len(recent)) + recent
    return [min_h + (max_h - min_h) * level for level in padded]
