import os
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
    def test_macos_modifier_only_hotkey_is_swallowed_on_press_and_release(self):
        # Modifiers arrive as flagsChanged events for both press and release.
        listener = self._listener("cmd_r", mode="push-to-talk")
        cmd_r = keyboard.Key.cmd_r
        event = Quartz.CGEventCreateKeyboardEvent(None, self._vk(cmd_r), True)
        listener._on_press(cmd_r)
        self.assertIsNone(listener._intercept_event(Quartz.kCGEventFlagsChanged, event))
        listener._on_release(cmd_r)
        release = Quartz.CGEventCreateKeyboardEvent(None, self._vk(cmd_r), False)
        self.assertIsNone(listener._intercept_event(Quartz.kCGEventFlagsChanged, release))
        other = Quartz.CGEventCreateKeyboardEvent(None, self._vk(keyboard.Key.cmd_l), True)
        listener._on_press(keyboard.Key.cmd_l)
        self.assertIs(listener._intercept_event(Quartz.kCGEventFlagsChanged, other), other)

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


@unittest.skipUnless(_PYNPUT_AVAILABLE, "pynput unavailable in this environment")
class UndoBindingTests(unittest.TestCase):
    """Second, optional hotkey binding for 'undo last dictation' (#45)."""

    def setUp(self):
        self.events: "queue.Queue[str]" = queue.Queue()
        self.listener = HotkeyListener(
            hotkey="ctrl+shift+space",
            mode="toggle",
            on_start=lambda: self.events.put("start"),
            on_stop=lambda: self.events.put("stop"),
        )
        self.listener.add_binding(
            "undo", "ctrl+shift+backspace", lambda: self.events.put("undo")
        )
        self.addCleanup(self.listener.stop)

    @staticmethod
    def _vk(key) -> int:
        return key.value.vk

    def _press_undo(self):
        for key in (keyboard.Key.ctrl, keyboard.Key.shift, keyboard.Key.backspace):
            self.listener._on_press(key)

    def test_ac1_given_undo_binding_when_its_combination_is_pressed_then_undo_fires_once(self):
        self._press_undo()
        self.assertEqual(self.events.get(timeout=0.5), "undo")
        self.listener._on_press(keyboard.Key.backspace)  # auto-repeat while held
        time.sleep(0.05)
        self.assertTrue(self.events.empty())

    def test_ac9_given_undo_binding_triggered_when_intercepting_then_its_key_is_swallowed(self):
        self._press_undo()
        vk = self._vk(keyboard.Key.backspace)
        self.assertTrue(self.listener._should_suppress(vk, is_key_down=True))
        for key in (keyboard.Key.backspace, keyboard.Key.shift, keyboard.Key.ctrl):
            self.listener._on_release(key)
        self.assertTrue(self.listener._should_suppress(vk, is_key_down=False))
        self.listener._on_press(keyboard.Key.backspace)  # plain Backspace afterwards
        self.assertFalse(self.listener._should_suppress(vk, is_key_down=True))

    def test_ac15_given_undo_binding_when_record_hotkey_pressed_then_recording_toggles(self):
        for key in (keyboard.Key.ctrl, keyboard.Key.shift, keyboard.Key.space):
            self.listener._on_press(key)
        self.assertEqual(self.events.get(timeout=0.5), "start")
        self.assertTrue(self.listener.is_recording)
        self.listener._on_release(keyboard.Key.space)
        self._press_undo()
        self.assertEqual(self.events.get(timeout=0.5), "undo")
        self.assertTrue(self.listener.is_recording)  # undo leaves recording alone
        self.listener._on_release(keyboard.Key.backspace)
        self.listener._on_press(keyboard.Key.space)
        self.assertEqual(self.events.get(timeout=0.5), "stop")

    def test_more_specific_binding_wins_when_one_contains_the_other(self):
        listener = HotkeyListener(
            hotkey="f1", mode="toggle",
            on_start=lambda: self.events.put("start"), on_stop=lambda: None,
        )
        self.addCleanup(listener.stop)
        listener.add_binding("undo", "shift+f1", lambda: self.events.put("undo"))
        listener._on_press(keyboard.Key.shift)
        listener._on_press(keyboard.Key.f1)
        self.assertEqual(self.events.get(timeout=0.5), "undo")
        time.sleep(0.05)
        self.assertTrue(self.events.empty())
        self.assertFalse(listener.is_recording)

    def test_ac11_given_undo_equal_to_record_hotkey_when_adding_then_it_is_rejected(self):
        listener = HotkeyListener(hotkey="ctrl+shift+space", on_start=None, on_stop=None)
        with self.assertRaises(HotkeyError):
            listener.add_binding("undo", "<ctrl>+<shift>+space", lambda: None)
        with self.assertRaises(HotkeyError):
            listener.add_binding("undo", "ctrl+nosuchkey", lambda: None)
        with self.assertRaises(HotkeyError):
            listener.add_binding("undo", "", lambda: None)
        self.assertEqual(len(listener._bindings), 1)

    def test_named_keys_parse_like_the_settings_recorder_writes_them(self):
        for name in ("backspace", "delete", "up", "home", "pageup", "pagedown"):
            with self.subTest(name=name):
                HotkeyListener(hotkey=f"ctrl+shift+{name}", on_start=None, on_stop=None)


@unittest.skipUnless(
    _PYNPUT_AVAILABLE and _QUARTZ_AVAILABLE, "pynput and Quartz only on macOS"
)
class OtherKeyHookTests(unittest.TestCase):
    """AC-5: user keystrokes after an insert invalidate it, the daemon's own do not."""

    OTHER_PID = 4242

    def setUp(self):
        self.other_keys = []
        self.undos: "queue.Queue[str]" = queue.Queue()
        self.listener = HotkeyListener(
            hotkey="ctrl+shift+space", on_start=lambda: None, on_stop=lambda: None,
            on_other_key=lambda: self.other_keys.append(1),
        )
        self.listener.add_binding("undo", "ctrl+shift+backspace", lambda: self.undos.put("undo"))
        self.listener._defer_injected = True  # as on macOS after start()
        self.addCleanup(self.listener.stop)

    def _event(self, key, down=True, pid=0):
        event = Quartz.CGEventCreateKeyboardEvent(None, getattr(key, "value", key).vk, down)
        Quartz.CGEventSetIntegerValueField(event, Quartz.kCGEventSourceUnixProcessID, pid)
        return event

    def _user(self, key, down=True):
        """A hardware keystroke: pynput callback first, then the intercept."""
        (self.listener._on_press if down else self.listener._on_release)(key, False)
        kind = Quartz.kCGEventKeyDown if down else Quartz.kCGEventKeyUp
        if key in (keyboard.Key.ctrl, keyboard.Key.shift):
            kind = Quartz.kCGEventFlagsChanged
        return self.listener._intercept_event(kind, self._event(key, down))

    def _injected(self, key, down=True, pid=None):
        pid = os.getpid() if pid is None else pid
        (self.listener._on_press if down else self.listener._on_release)(key, True)
        kind = Quartz.kCGEventKeyDown if down else Quartz.kCGEventKeyUp
        return self.listener._intercept_event(kind, self._event(key, down, pid))

    def test_ac5_given_a_user_letter_or_arrow_when_pressed_then_other_key_fires(self):
        for key in (keyboard.KeyCode.from_vk(7), keyboard.Key.left, keyboard.Key.enter):
            self.assertIsNotNone(self._user(key))
        self.assertEqual(len(self.other_keys), 3)

    def test_ac5_given_a_plain_backspace_when_pressed_then_other_key_fires(self):
        self.assertIsNotNone(self._user(keyboard.Key.backspace))
        self.assertEqual(len(self.other_keys), 1)

    def test_ac5_given_modifiers_only_when_pressed_then_nothing_is_invalidated(self):
        self._user(keyboard.Key.shift)
        self._user(keyboard.Key.shift, down=False)
        self.assertEqual(self.other_keys, [])

    def test_ac5_given_the_undo_hotkey_when_pressed_then_it_does_not_invalidate(self):
        self._user(keyboard.Key.ctrl)
        self._user(keyboard.Key.shift)
        self.assertIsNone(self._user(keyboard.Key.backspace))
        self.assertEqual(self.undos.get(timeout=0.5), "undo")
        self.assertEqual(self.other_keys, [])

    def test_ac5_given_own_injected_keys_when_seen_then_they_pass_and_do_not_invalidate(self):
        for key in (keyboard.Key.cmd, keyboard.KeyCode.from_vk(9), keyboard.Key.backspace):
            self.assertIsNotNone(self._injected(key))
            self.assertIsNotNone(self._injected(key, down=False))
        self.assertEqual(self.other_keys, [])

    def test_ac1_given_undo_held_when_own_backspaces_are_sent_then_they_pass_without_retrigger(self):
        self._user(keyboard.Key.ctrl)
        self._user(keyboard.Key.shift)
        self._user(keyboard.Key.backspace)
        self.assertEqual(self.undos.get(timeout=0.5), "undo")
        for _ in range(3):
            self.assertIsNotNone(self._injected(keyboard.Key.backspace))
            self.assertIsNotNone(self._injected(keyboard.Key.backspace, down=False))
        time.sleep(0.05)
        self.assertTrue(self.undos.empty())
        # The user's own Backspace is still held, so its key-up stays swallowed.
        self.assertIsNone(self._user(keyboard.Key.backspace, down=False))

    def test_given_another_app_injects_keys_when_seen_then_they_count_as_user_input(self):
        self.assertIsNotNone(self._injected(keyboard.KeyCode.from_vk(7), pid=self.OTHER_PID))
        self.assertEqual(len(self.other_keys), 1)


class PynputPinTests(unittest.TestCase):
    """pynput passes ``injected`` to callbacks only from 1.8 on (#45)."""

    def test_ac1_ac5_given_pyproject_when_reading_pynput_pin_then_minimum_is_1_8(self):
        import re
        import tomllib
        from pathlib import Path

        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        deps = tomllib.loads(pyproject.read_text())["project"]["dependencies"]
        pin = next(d for d in deps if d.startswith("pynput"))
        match = re.fullmatch(r"pynput>=(\d+)\.(\d+)(?:\.\d+)?", pin.replace(" ", ""))
        self.assertIsNotNone(match, pin)
        self.assertGreaterEqual((int(match[1]), int(match[2])), (1, 8), pin)



@unittest.skipUnless(_PYNPUT_AVAILABLE, "pynput unavailable in this environment")
class MixedModifierHotkeyTests(unittest.TestCase):
    """#70: a hotkey mixing generic and side-specific modifiers keeps every key."""

    def _listener(self, hotkey):
        self.events: "queue.Queue[str]" = queue.Queue()
        listener = HotkeyListener(
            hotkey=hotkey, mode="toggle",
            on_start=lambda: self.events.put("start"),
            on_stop=lambda: self.events.put("stop"),
        )
        self.addCleanup(listener.stop)
        return listener

    def _fired(self) -> bool:
        try:
            self.events.get(timeout=0.3)
        except queue.Empty:
            return False
        return True

    def _press(self, listener, *keys):
        for key in keys:
            listener._on_press(key)

    def test_ac1_given_ctrl_cmd_r_when_parsed_then_both_keys_are_bound(self):
        listener = self._listener("ctrl+cmd_r")
        self.assertEqual(
            listener._record.keys, frozenset({keyboard.Key.ctrl, keyboard.Key.cmd_r})
        )

    def test_ac1_given_ctrl_cmd_r_when_cmd_r_alone_then_it_does_not_fire(self):
        listener = self._listener("ctrl+cmd_r")
        self._press(listener, keyboard.Key.cmd_r)
        self.assertFalse(self._fired())

    def test_ac2_given_ctrl_cmd_r_when_either_ctrl_and_cmd_r_then_it_fires(self):
        for ctrl in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            with self.subTest(ctrl=ctrl):
                listener = self._listener("ctrl+cmd_r")
                self._press(listener, ctrl, keyboard.Key.cmd_r)
                self.assertTrue(self._fired())

    def test_ac3_given_ctrl_cmd_r_when_ctrl_and_left_cmd_then_it_does_not_fire(self):
        listener = self._listener("ctrl+cmd_r")
        self._press(listener, keyboard.Key.ctrl, keyboard.Key.cmd_l)
        self.assertFalse(self._fired())

    def test_ac3_given_ctrl_cmd_r_when_bound_then_vks_cover_both_ctrls_and_only_right_cmd(self):
        listener = self._listener("ctrl+cmd_r")
        vk = lambda key: key.value.vk  # noqa: E731
        vks = listener._record.vks
        self.assertTrue({vk(keyboard.Key.ctrl_l), vk(keyboard.Key.ctrl_r)} <= vks)
        self.assertIn(vk(keyboard.Key.cmd_r), vks)
        self.assertNotIn(vk(keyboard.Key.cmd_l), vks)

    def test_ac4_given_generic_and_side_variant_of_one_modifier_when_parsed_then_rejected(self):
        for hotkey in ("ctrl+ctrl_r", "ctrl+ctrl_l", "cmd_r+cmd+space"):
            with self.subTest(hotkey=hotkey):
                with self.assertRaises(HotkeyError):
                    self._listener(hotkey)

    def test_unchanged_given_cmd_r_alone_when_left_cmd_pressed_then_it_does_not_fire(self):
        listener = self._listener("cmd_r")
        self._press(listener, keyboard.Key.cmd_l)
        self.assertFalse(self._fired())
        self._press(listener, keyboard.Key.cmd_r)
        self.assertTrue(self._fired())

    def test_unchanged_given_generic_combo_when_right_side_keys_then_it_fires(self):
        listener = self._listener("ctrl+shift+space")
        self._press(listener, keyboard.Key.ctrl_r, keyboard.Key.shift_r, keyboard.Key.space)
        self.assertTrue(self._fired())


if __name__ == "__main__":
    unittest.main()
