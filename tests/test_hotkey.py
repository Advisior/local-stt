import queue
import time
import unittest
from unittest import mock

try:
    from pynput import keyboard
    _PYNPUT_AVAILABLE = True
except Exception:
    keyboard = None
    _PYNPUT_AVAILABLE = False

try:
    import Quartz
    _QUARTZ_AVAILABLE = True
except Exception:
    Quartz = None
    _QUARTZ_AVAILABLE = False

from claude_stt.hotkey import HotkeyListener
from claude_stt.errors import HotkeyError


@unittest.skipUnless(_PYNPUT_AVAILABLE, "pynput unavailable in this environment")
class HotkeyListenerTests(unittest.TestCase):
    def _press_hotkey(self, listener: HotkeyListener) -> None:
        for key in listener._hotkey_keys:
            listener._on_press(key)

    def _release_hotkey(self, listener: HotkeyListener) -> None:
        key = self._primary_key(listener)
        listener._on_release(key)

    def _primary_key(self, listener: HotkeyListener):
        if keyboard.Key.space in listener._hotkey_keys:
            return keyboard.Key.space
        return next(iter(listener._hotkey_keys))

    def _next_event(self, events: "queue.Queue[str]", timeout: float = 0.5) -> str:
        return events.get(timeout=timeout)

    def test_toggle_mode_debounces_hotkey_repeat(self):
        events: "queue.Queue[str]" = queue.Queue()

        listener = HotkeyListener(
            hotkey="ctrl+shift+space",
            mode="toggle",
            on_start=lambda: events.put("start"),
            on_stop=lambda: events.put("stop"),
        )

        self._press_hotkey(listener)
        self.assertEqual(self._next_event(events), "start")

        # Repeat press while still held should not toggle again.
        listener._on_press(self._primary_key(listener))
        time.sleep(0.05)
        self.assertTrue(events.empty())

        self._release_hotkey(listener)
        listener._on_press(self._primary_key(listener))
        self.assertEqual(self._next_event(events), "stop")

    def test_push_to_talk_stops_on_release(self):
        events: "queue.Queue[str]" = queue.Queue()

        listener = HotkeyListener(
            hotkey="ctrl+shift+space",
            mode="push-to-talk",
            on_start=lambda: events.put("start"),
            on_stop=lambda: events.put("stop"),
        )

        self._press_hotkey(listener)
        self.assertEqual(self._next_event(events), "start")

        self._release_hotkey(listener)
        self.assertEqual(self._next_event(events), "stop")

    def test_invalid_hotkey_rejected(self):
        with self.assertRaises(HotkeyError):
            HotkeyListener(hotkey="")
        with self.assertRaises(HotkeyError):
            HotkeyListener(hotkey="ctrl+unknownkey")

    def test_macos_suppression_callback_reaches_pynput(self):
        # pynput silently drops unknown kwargs; only darwin_-prefixed options
        # reach the macOS backend. A bare intercept= left suppression dead.
        listener = HotkeyListener(on_start=lambda: None, on_stop=lambda: None)
        backend = mock.Mock()
        backend.is_alive.return_value = True
        with mock.patch("claude_stt.hotkey.platform.system", return_value="Darwin"), \
                mock.patch.object(keyboard, "Listener", return_value=backend) as ctor:
            self.assertTrue(listener.start())
            listener.stop()
        kwargs = ctor.call_args.kwargs
        self.assertEqual(kwargs["darwin_intercept"], listener._intercept_event)
        self.assertNotIn("intercept", kwargs)


    def _listener(self, hotkey: str, mode: str = "toggle") -> HotkeyListener:
        return HotkeyListener(
            hotkey=hotkey, on_start=lambda: None, on_stop=lambda: None, mode=mode
        )

    @staticmethod
    def _vk(key) -> int:
        return key.value.vk

    def test_plain_key_of_a_combination_passes_through(self):
        # Regression: matching the keycode alone swallowed every Space.
        listener = self._listener("ctrl+shift+space")
        space = keyboard.Key.space
        listener._on_press(space)
        self.assertFalse(listener._should_suppress(self._vk(space), is_key_down=True))
        listener._on_release(space)
        self.assertFalse(listener._should_suppress(self._vk(space), is_key_down=False))

    def test_triggered_combination_swallows_its_key_until_release(self):
        listener = self._listener("ctrl+shift+space")
        ctrl, shift, space = keyboard.Key.ctrl, keyboard.Key.shift, keyboard.Key.space
        for modifier in (ctrl, shift):
            listener._on_press(modifier)
            self.assertFalse(listener._should_suppress(self._vk(modifier), is_key_down=False))
        listener._on_press(space)
        self.assertTrue(listener._should_suppress(self._vk(space), is_key_down=True))
        listener._on_press(space)
        self.assertTrue(
            listener._should_suppress(self._vk(space), is_key_down=True, is_repeat=True)
        )
        listener._on_release(space)
        self.assertTrue(listener._should_suppress(self._vk(space), is_key_down=False))
        # Modifiers were passed through on press, so their release passes too.
        for modifier in (ctrl, shift):
            listener._on_release(modifier)
            self.assertFalse(listener._should_suppress(self._vk(modifier), is_key_down=False))
        listener._on_press(space)
        self.assertFalse(listener._should_suppress(self._vk(space), is_key_down=True))

    def test_single_key_hotkey_is_swallowed_on_press_repeat_and_release(self):
        listener = self._listener("f1", mode="push-to-talk")
        f1 = keyboard.Key.f1
        for _ in range(2):
            listener._on_press(f1)
            self.assertTrue(listener._should_suppress(self._vk(f1), is_key_down=True))
            listener._on_press(f1)
            self.assertTrue(
                listener._should_suppress(self._vk(f1), is_key_down=True, is_repeat=True)
            )
            listener._on_release(f1)
            self.assertTrue(listener._should_suppress(self._vk(f1), is_key_down=False))

    def test_key_stays_swallowed_when_a_modifier_is_released_first(self):
        listener = self._listener("ctrl+shift+space")
        ctrl, shift, space = keyboard.Key.ctrl, keyboard.Key.shift, keyboard.Key.space
        for key in (ctrl, shift, space):
            listener._on_press(key)
        self.assertTrue(listener._should_suppress(self._vk(space), is_key_down=True))
        listener._on_release(ctrl)
        self.assertFalse(listener._should_suppress(self._vk(ctrl), is_key_down=False))
        listener._on_press(space)  # Space still held, auto-repeat continues
        self.assertTrue(
            listener._should_suppress(self._vk(space), is_key_down=True, is_repeat=True)
        )
        listener._on_release(space)
        self.assertTrue(listener._should_suppress(self._vk(space), is_key_down=False))

    def test_missed_release_does_not_eat_the_next_keystroke(self):
        listener = self._listener("ctrl+shift+space")
        ctrl, shift, space = keyboard.Key.ctrl, keyboard.Key.shift, keyboard.Key.space
        for key in (ctrl, shift, space):
            listener._on_press(key)
        self.assertTrue(listener._should_suppress(self._vk(space), is_key_down=True))
        for key in (ctrl, shift, space):
            listener._on_release(key)  # the key-up never reached the intercept
        listener._on_press(space)
        self.assertFalse(listener._should_suppress(self._vk(space), is_key_down=True))

    @unittest.skipUnless(_QUARTZ_AVAILABLE, "Quartz only on macOS")
    def test_macos_intercept_passes_plain_space(self):
        listener = self._listener("ctrl+shift+space")
        event = Quartz.CGEventCreateKeyboardEvent(None, self._vk(keyboard.Key.space), True)
        listener._on_press(keyboard.Key.space)
        self.assertIs(listener._intercept_event(Quartz.kCGEventKeyDown, event), event)

    @unittest.skipUnless(_QUARTZ_AVAILABLE, "Quartz only on macOS")
    def test_macos_intercept_reads_autorepeat_flag(self):
        listener = self._listener("ctrl+shift+space")
        ctrl, shift, space = keyboard.Key.ctrl, keyboard.Key.shift, keyboard.Key.space
        vk = self._vk(space)
        for key in (ctrl, shift, space):
            listener._on_press(key)
        press = Quartz.CGEventCreateKeyboardEvent(None, vk, True)
        self.assertIsNone(listener._intercept_event(Quartz.kCGEventKeyDown, press))
        listener._on_release(ctrl)
        repeat = Quartz.CGEventCreateKeyboardEvent(None, vk, True)
        Quartz.CGEventSetIntegerValueField(repeat, Quartz.kCGKeyboardEventAutorepeat, 1)
        listener._on_press(space)
        self.assertIsNone(listener._intercept_event(Quartz.kCGEventKeyDown, repeat))


if __name__ == "__main__":
    unittest.main()
