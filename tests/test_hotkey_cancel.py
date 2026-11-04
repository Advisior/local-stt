"""Esc cancels a running recording (#60 AC-8, AC-9)."""

import platform
import sys
import unittest
from unittest import mock

from claude_stt.hotkey import _PYNPUT_AVAILABLE, HotkeyListener

if _PYNPUT_AVAILABLE:
    from pynput import keyboard


@unittest.skipUnless(_PYNPUT_AVAILABLE, "pynput unavailable in this environment")
class EscCancelTests(unittest.TestCase):
    def _listener(self, mode="toggle"):
        self.events = []
        listener = HotkeyListener(
            hotkey="ctrl+shift+space",
            mode=mode,
            on_start=lambda: self.events.append("start"),
            on_stop=lambda: self.events.append("stop"),
            on_cancel=lambda: self.events.append("cancel"),
        )
        listener._enqueue_event = lambda label, cb: cb and cb()
        self.addCleanup(listener.stop)
        return listener

    def _press(self, listener, *keys):
        for key in keys:
            listener._handle_press(key)

    def _release(self, listener, *keys):
        for key in keys:
            listener._handle_release(key)

    def test_ac8_given_armed_when_esc_pressed_then_cancel_fires_once_and_disarms(self):
        listener = self._listener()
        self._press(listener, keyboard.Key.ctrl, keyboard.Key.shift, keyboard.Key.space)
        self._release(listener, keyboard.Key.space, keyboard.Key.shift, keyboard.Key.ctrl)
        listener.cancel_armed = True
        self._press(listener, keyboard.Key.esc)
        self._release(listener, keyboard.Key.esc)
        self._press(listener, keyboard.Key.esc)
        self.assertEqual(self.events, ["start", "cancel"])
        self.assertFalse(listener.cancel_armed)
        self.assertFalse(listener.is_recording)

    def test_ac8_given_toggle_mode_after_cancel_when_hotkey_pressed_then_a_new_recording_starts(self):
        listener = self._listener()
        hotkey = (keyboard.Key.ctrl, keyboard.Key.shift, keyboard.Key.space)
        self._press(listener, *hotkey)
        self._release(listener, *reversed(hotkey))
        listener.cancel_armed = True
        self._press(listener, keyboard.Key.esc)
        self._release(listener, keyboard.Key.esc)
        self._press(listener, *hotkey)
        self.assertEqual(self.events, ["start", "cancel", "start"])

    def test_ac8_given_push_to_talk_held_when_esc_pressed_then_release_does_not_stop(self):
        listener = self._listener(mode="push-to-talk")
        hotkey = (keyboard.Key.ctrl, keyboard.Key.shift, keyboard.Key.space)
        self._press(listener, *hotkey)
        listener.cancel_armed = True
        self._press(listener, keyboard.Key.esc)
        self._release(listener, keyboard.Key.esc, *reversed(hotkey))
        self.assertEqual(self.events, ["start", "cancel"])

    def test_ac9_given_not_armed_when_esc_pressed_then_nothing_fires(self):
        listener = self._listener()
        self._press(listener, keyboard.Key.esc)
        self.assertEqual(self.events, [])

    def test_ac9_given_armed_when_esc_with_a_modifier_then_nothing_fires(self):
        listener = self._listener()
        listener.cancel_armed = True
        self._press(listener, keyboard.Key.cmd, keyboard.Key.alt, keyboard.Key.esc)
        self.assertEqual(self.events, [])
        self.assertTrue(listener.cancel_armed)

    def test_ac9_given_no_cancel_callback_when_esc_pressed_then_nothing_fires(self):
        listener = HotkeyListener(hotkey="ctrl+shift+space", on_start=None, on_stop=None)
        self.addCleanup(listener.stop)
        listener.cancel_armed = True
        listener._handle_press(keyboard.Key.esc)
        self.assertTrue(listener.cancel_armed)


class _FakeQuartz:
    kCGEventKeyDown, kCGEventKeyUp, kCGEventFlagsChanged = 10, 11, 12
    kCGEventSourceUnixProcessID, kCGKeyboardEventAutorepeat, kCGKeyboardEventKeycode = 41, 8, 9

    def CGEventGetIntegerValueField(self, event, field):
        return {
            self.kCGKeyboardEventKeycode: event["vk"],
            self.kCGKeyboardEventAutorepeat: event.get("repeat", 0),
            self.kCGEventSourceUnixProcessID: 0,
        }[field]


@unittest.skipUnless(
    _PYNPUT_AVAILABLE and platform.system() == "Darwin", "macOS keycodes (pynput darwin backend)"
)
class EscSwallowTests(unittest.TestCase):
    ESC = 53

    def setUp(self):
        self.quartz = _FakeQuartz()
        patcher = mock.patch.dict(sys.modules, {"Quartz": self.quartz})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cancelled = []
        self.listener = HotkeyListener(
            hotkey="ctrl+shift+space", mode="toggle", on_start=None, on_stop=None,
            on_cancel=lambda: self.cancelled.append(1),
        )
        self.listener._enqueue_event = lambda label, cb: cb and cb()
        self.addCleanup(self.listener.stop)

    def _esc(self, down=True, repeat=0):
        (self.listener._on_press if down else self.listener._on_release)(keyboard.Key.esc, False)
        kind = self.quartz.kCGEventKeyDown if down else self.quartz.kCGEventKeyUp
        return self.listener._intercept_event(kind, {"vk": self.ESC, "repeat": repeat})

    def test_ac8_given_armed_when_esc_pressed_then_down_repeat_and_up_are_swallowed(self):
        self.listener.cancel_armed = True
        self.assertIsNone(self._esc())
        self.assertIsNone(self._esc(repeat=1))
        self.assertIsNone(self._esc(down=False))
        self.assertEqual(self.cancelled, [1])

    def test_ac9_given_cancel_done_when_esc_pressed_again_then_it_passes(self):
        self.listener.cancel_armed = True
        self._esc()
        self._esc(down=False)
        self.assertIsNotNone(self._esc())
        self.assertIsNotNone(self._esc(down=False))

    def test_ac9_given_not_armed_when_esc_pressed_then_it_passes(self):
        self.assertIsNotNone(self._esc())
        self.assertIsNotNone(self._esc(down=False))
        self.assertEqual(self.cancelled, [])


if __name__ == "__main__":
    unittest.main()
