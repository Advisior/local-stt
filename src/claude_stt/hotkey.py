"""Global hotkey detection using pynput."""

import logging
import os
import platform
import queue
import threading
from dataclasses import dataclass
from typing import Callable, Optional

try:
    from pynput import keyboard
    _PYNPUT_AVAILABLE = True
    _PYNPUT_IMPORT_ERROR: Exception | None = None
except Exception as exc:
    keyboard = None
    _PYNPUT_AVAILABLE = False
    _PYNPUT_IMPORT_ERROR = exc

from .errors import HotkeyError
from .hotkey_darwin import MacInterceptMixin

RECORD = "record"

@dataclass
class _Binding:
    """One registered key combination."""

    label: str
    keys: frozenset
    generic: frozenset  # keys that accept either side (e.g. "ctrl"); "cmd_r" stays one side
    vks: frozenset  # virtual keycodes, used to swallow its events on macOS
    active: bool = False  # full combination currently held


class HotkeyListener(MacInterceptMixin):
    """Listens for global hotkey events.

    The record hotkey supports push-to-talk (hold to record) and toggle modes.
    Further bindings (add_binding) fire their callback once per press.
    """

    def __init__(
        self,
        hotkey: str = "<ctrl>+<shift>+space",
        on_start: Optional[Callable[[], None]] = None,
        on_stop: Optional[Callable[[], None]] = None,
        mode: str = "push-to-talk",
        on_other_key: Optional[Callable[[], None]] = None,
    ):
        """Initialize the hotkey listener.

        Args:
            hotkey: Hotkey combination string (pynput format).
            on_start: Callback when recording should start.
            on_stop: Callback when recording should stop.
            mode: "push-to-talk" or "toggle".
            on_other_key: macOS only. Called on the listener thread for every
                key-down that reaches the focused app and was not sent by this
                process (no modifiers, no hotkey keys). Must return quickly.
        """
        self.hotkey_str = hotkey
        self.on_start = on_start
        self.on_stop = on_stop
        self.mode = mode
        self.on_other_key = on_other_key

        self._listener: Optional[keyboard.Listener] = None
        self._is_recording = False
        self._pressed_keys: set = set()
        self._suppressed_vks: set[int] = set()
        # Character keys carry their keycode only on the press event (it depends
        # on the keyboard layout): normalized key -> vk while the key is held.
        self._held_char_vks: dict = {}
        self._bindings: list[_Binding] = []
        self._callbacks: dict[str, Optional[Callable[[], None]]] = {}
        # macOS: pynput reports injected events before the intercept sees the
        # raw event with its source PID; hold them back until then.
        self._defer_injected = False
        self._pending_injected: list[tuple[bool, object]] = []
        self._own_pid = os.getpid()
        self._lock = threading.Lock()
        self._logger = logging.getLogger(__name__)
        self._event_queue: "queue.Queue[Optional[tuple[str, Optional[Callable[[], None]]]]]" = (
            queue.Queue(maxsize=8)
        )
        self._worker_thread: Optional[threading.Thread] = None
        self._worker_stop = threading.Event()

        if not _PYNPUT_AVAILABLE:
            message = "pynput unavailable; hotkeys cannot be registered"
            if _PYNPUT_IMPORT_ERROR:
                message = f"{message}: {_PYNPUT_IMPORT_ERROR}"
            raise HotkeyError(message)

        record = self._make_binding(RECORD, hotkey)
        self._bindings.append(record)
        self._hotkey_keys = set(record.keys)

    @property
    def _record(self) -> _Binding:
        return self._bindings[0]

    def _make_binding(self, label: str, hotkey: str) -> _Binding:
        keys, generic = self._parse_hotkey(hotkey)
        if not keys:
            raise HotkeyError(f"Hotkey '{hotkey}' did not map to any keys")
        sides = {s for k in keys for s in (self._both_sides(k) if k in generic else (k,))}
        vks = frozenset(
            vk
            for vk in (getattr(getattr(k, "value", k), "vk", None) for k in sides)
            if vk is not None
        )
        return _Binding(label, frozenset(keys), frozenset(generic), vks)

    @staticmethod
    def _both_sides(key) -> tuple:
        """A generic modifier stands for its left and right key."""
        for generic in ("ctrl", "shift", "alt", "cmd"):
            if key == getattr(keyboard.Key, generic):
                return (
                    key,
                    getattr(keyboard.Key, f"{generic}_l"),
                    getattr(keyboard.Key, f"{generic}_r"),
                )
        return (key,)

    def add_binding(self, label: str, hotkey: str, callback: Callable[[], None]) -> None:
        """Register another hotkey that calls ``callback`` once per press.

        Raises:
            HotkeyError: if the hotkey does not parse or equals an existing one.
        """
        binding = self._make_binding(label, hotkey)
        with self._lock:
            for existing in self._bindings:
                if existing.keys == binding.keys:
                    raise HotkeyError(
                        f"Hotkey '{hotkey}' is already the {existing.label} hotkey"
                    )
            self._bindings.append(binding)
            self._callbacks[label] = callback

    # Side-specific modifier keys that bypass normal normalization
    _SIDE_SPECIFIC_KEYS = {
        "cmd_r": "cmd_r", "cmd_right": "cmd_r", "right_cmd": "cmd_r",
        "cmd_l": "cmd_l", "cmd_left": "cmd_l", "left_cmd": "cmd_l",
        "ctrl_r": "ctrl_r", "ctrl_right": "ctrl_r", "right_ctrl": "ctrl_r",
        "ctrl_l": "ctrl_l", "ctrl_left": "ctrl_l", "left_ctrl": "ctrl_l",
        "shift_r": "shift_r", "shift_right": "shift_r", "right_shift": "shift_r",
        "shift_l": "shift_l", "shift_left": "shift_l", "left_shift": "shift_l",
        "alt_r": "alt_r", "alt_right": "alt_r", "right_alt": "alt_r",
        "alt_l": "alt_l", "alt_left": "alt_l", "left_alt": "alt_l",
    }

    def _parse_hotkey(self, hotkey_str: str) -> tuple[set, set]:
        """Parse hotkey string to a set of keys.

        Args:
            hotkey_str: Hotkey like "<ctrl>+<shift>+space" or "ctrl+shift+space"
                        or "cmd_r" for side-specific single modifier keys.

        Returns:
            Set of key objects, and the subset that accepts either side.
        """
        if not hotkey_str.strip():
            raise HotkeyError("Hotkey cannot be empty")

        # Side-specific modifiers (e.g. "cmd_r") match only their side; the
        # remaining parts ("ctrl" in "ctrl+cmd_r") are parsed as usual.
        parts = [p.strip().lower() for p in hotkey_str.split("+") if p.strip()]
        side_keys = set()
        rest = []
        for part in parts:
            if part in self._SIDE_SPECIFIC_KEYS:
                key_name = self._SIDE_SPECIFIC_KEYS[part]
                try:
                    side_keys.add(getattr(keyboard.Key, key_name))
                except AttributeError:
                    raise HotkeyError(f"Key '{part}' not supported by pynput")
            else:
                rest.append(part)

        if not rest:
            return side_keys, set()

        try:
            normalized = self._normalize_hotkey_string("+".join(rest))
            keys = keyboard.HotKey.parse(normalized)
        except Exception as exc:
            raise HotkeyError(f"Invalid hotkey '{hotkey_str}': {exc}") from exc

        normalized_keys: set = set()
        for key in keys:
            normalized_key = self._normalize_key(key)
            if normalized_key is not None:
                normalized_keys.add(self._collapse_side(normalized_key))
        if any(self._collapse_side(k) in normalized_keys for k in side_keys):
            raise HotkeyError(
                f"Hotkey '{hotkey_str}' names a modifier both generic and side-specific"
            )
        return normalized_keys | side_keys, normalized_keys

    def _normalize_hotkey_string(self, hotkey_str: str) -> str:
        parts = [part.strip() for part in hotkey_str.split("+") if part.strip()]
        if not parts:
            return hotkey_str

        key_map = {
            "ctrl": "<ctrl>",
            "control": "<ctrl>",
            "shift": "<shift>",
            "alt": "<alt>",
            "cmd": "<cmd>",
            "command": "<cmd>",
            "space": "<space>",
            "enter": "<enter>",
            "return": "<enter>",
            "tab": "<tab>",
            "esc": "<esc>",
            "escape": "<esc>",
            # Names the menu bar app's hotkey recorder writes
            "pageup": "<page_up>",
            "pagedown": "<page_down>",
        }

        normalized_parts = []
        for part in parts:
            lowered = part.lower()
            if lowered.startswith("<") and lowered.endswith(">"):
                normalized_parts.append(lowered)
                continue
            if lowered in key_map:
                normalized_parts.append(key_map[lowered])
                continue
            if lowered.startswith("f") and lowered[1:].isdigit():
                normalized_parts.append(f"<{lowered}>")
                continue
            if len(lowered) > 1 and lowered in keyboard.Key.__members__:
                normalized_parts.append(f"<{lowered}>")  # backspace, delete, up, ...
                continue
            normalized_parts.append(lowered)

        return "+".join(normalized_parts)

    def _ensure_worker(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._worker_stop.clear()
        self._worker_thread = threading.Thread(
            target=self._event_worker,
            name="claude-stt-hotkey-worker",
            daemon=True,
        )
        self._worker_thread.start()

    def _event_worker(self) -> None:
        while not self._worker_stop.is_set():
            try:
                item = self._event_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is None:
                return
            label, callback = item
            if not callback:
                continue
            try:
                callback()
            except Exception:
                self._logger.exception("Hotkey callback failed: %s", label)

    def _enqueue_event(self, label: str, callback: Optional[Callable[[], None]]) -> None:
        self._ensure_worker()
        try:
            self._event_queue.put_nowait((label, callback))
        except queue.Full:
            self._logger.warning("Dropping hotkey event '%s'; queue full", label)

    def _normalize_key(self, key) -> Optional[object]:
        """Normalize a key to a comparable form."""
        if hasattr(key, "char") and key.char:
            if key.char == " ":
                return keyboard.Key.space
            if key.char in ("\n", "\r"):
                return keyboard.Key.enter
            return keyboard.KeyCode.from_char(key.char.lower())

        if hasattr(key, "vk") and key.vk is not None:
            # Normalize KeyCode(vk=...) to Key enum when possible (Linux/X11).
            try:
                for member in keyboard.Key:
                    value = getattr(member, "value", None)
                    if hasattr(value, "vk") and value.vk == key.vk:
                        return member
            except Exception:
                pass

            if platform.system() == "Darwin":
                mac_vk_map = {
                    49: keyboard.Key.space,
                    36: keyboard.Key.enter,
                    48: keyboard.Key.tab,
                    53: keyboard.Key.esc,
                }
                if key.vk in mac_vk_map:
                    return mac_vk_map[key.vk]

        return key

    @staticmethod
    def _collapse_side(key):
        """Map left/right modifier variants to the generic modifier."""
        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            return keyboard.Key.ctrl
        if key in (keyboard.Key.shift_l, keyboard.Key.shift_r):
            return keyboard.Key.shift
        if key in (keyboard.Key.alt_l, keyboard.Key.alt_r):
            return keyboard.Key.alt
        if key in (keyboard.Key.cmd_l, keyboard.Key.cmd_r):
            return keyboard.Key.cmd

        return key

    def _view(self, key, binding: _Binding):
        collapsed = self._collapse_side(key)
        return collapsed if collapsed in binding.generic else key

    def _on_press(self, key, injected: bool = False):
        """Handle key press event (pynput passes ``injected`` since 1.8)."""
        if injected and self._defer_injected:
            self._pending_injected.append((True, key))
            return
        self._handle_press(key)

    def _on_release(self, key, injected: bool = False):
        """Handle key release event."""
        if injected and self._defer_injected:
            self._pending_injected.append((False, key))
            return
        self._handle_release(key)

    def _handle_press(self, key):
        normalized = self._normalize_key(key)
        if normalized is None:
            return

        with self._lock:
            self._pressed_keys.add(normalized)
            vk = getattr(key, "vk", None)
            if getattr(normalized, "char", None) and vk is not None:
                self._held_char_vks[normalized] = vk
            matched = [
                b for b in self._bindings
                if not b.active
                and b.keys.issubset({self._view(k, b) for k in self._pressed_keys})
            ]
            if not matched:
                return
            # "shift+f1" must not also fire "f1": the larger combination wins.
            winner = max(matched, key=lambda b: len(b.keys))
            for binding in matched:
                binding.active = True
            if winner.label == RECORD:
                self._fire_record()
            else:
                self._enqueue_event(winner.label, self._callbacks.get(winner.label))
        # Event suppression is handled by _intercept_event (macOS) via darwin_intercept=

    def _fire_record(self) -> None:
        """Start or stop recording. Call with the lock held."""
        if self.mode == "toggle":
            # Toggle mode: press to start/stop
            if not self._is_recording:
                self._is_recording = True
                self._enqueue_event("start", self.on_start)
            else:
                self._is_recording = False
                self._enqueue_event("stop", self.on_stop)
        elif not self._is_recording:
            # Push-to-talk: press to start
            self._is_recording = True
            self._enqueue_event("start", self.on_start)

    def _handle_release(self, key):
        normalized = self._normalize_key(key)
        if normalized is None:
            return

        with self._lock:
            self._pressed_keys.discard(normalized)
            self._held_char_vks.pop(normalized, None)
            for binding in self._bindings:
                if self._view(normalized, binding) in binding.keys:
                    binding.active = False

            # In push-to-talk mode, release any hotkey key to stop
            if self.mode == "push-to-talk" and self._is_recording:
                if self._view(normalized, self._record) in self._record.keys:
                    self._is_recording = False
                    self._enqueue_event("stop", self.on_stop)
        # Event suppression is handled by _intercept_event (macOS) via darwin_intercept=

    def start(self) -> bool:
        """Start listening for hotkeys.

        Returns:
            True if listener started successfully.
        """
        if not _PYNPUT_AVAILABLE:
            self._logger.error("pynput unavailable; cannot start hotkey listener")
            return False
        if self._listener is not None:
            return True

        try:
            self._defer_injected = platform.system() == "Darwin"
            self._listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
                # Must be darwin_intercept: pynput only picks up platform
                # options by their prefix and silently drops a bare
                # intercept=, so suppression would never run and the hotkey
                # would also reach the focused app.
                darwin_intercept=self._intercept_event if platform.system() == "Darwin" else None,
            )
            self._listener.start()
            self._ensure_worker()
            if not self._listener.is_alive():
                self._logger.error("Hotkey listener failed to start")
                self.stop()
                return False
            return True
        except Exception as e:
            self._logger.error("Failed to start hotkey listener: %s", e)
            return False

    def stop(self):
        """Stop listening for hotkeys."""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
            with self._lock:
                self._pressed_keys.clear()
                self._suppressed_vks.clear()
                self._held_char_vks.clear()
                self._pending_injected.clear()
                for binding in self._bindings:
                    binding.active = False
            self._is_recording = False
        self._worker_stop.set()
        try:
            self._event_queue.put_nowait(None)
        except queue.Full:
            pass
        if self._worker_thread:
            self._worker_thread.join(timeout=1.0)
            if self._worker_thread.is_alive():
                self._logger.warning("Hotkey worker did not exit cleanly")
            self._worker_thread = None

    def is_running(self) -> bool:
        """Check if listener is running."""
        return self._listener is not None and self._listener.is_alive()

    @property
    def is_recording(self) -> bool:
        """Check if currently in recording state."""
        return self._is_recording
