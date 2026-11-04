"""macOS event-tap suppression tests for hotkey_darwin.MacInterceptMixin (#41)."""

import platform
import sys
import types
import unittest
from unittest import mock

try:
    from pynput import keyboard
    _PYNPUT_AVAILABLE = True
except Exception:
    keyboard = None
    _PYNPUT_AVAILABLE = False

from claude_stt.hotkey import HotkeyListener


class _FakeQuartz(types.ModuleType):
    """Stand-in for the Quartz functions _intercept_event uses; events are dicts."""

    kCGEventKeyDown, kCGEventKeyUp, kCGEventFlagsChanged = 10, 11, 12
    kCGEventSourceUnixProcessID, kCGKeyboardEventAutorepeat, kCGKeyboardEventKeycode = 41, 8, 9

    def __init__(self, flags_error: Exception | None = None, with_flags: bool = True):
        super().__init__("Quartz")
        self._flags_error = flags_error
        if with_flags:
            self.CGEventGetFlags = self._get_flags

    def CGEventGetIntegerValueField(self, event, field):
        return {
            self.kCGKeyboardEventKeycode: event["vk"],
            self.kCGKeyboardEventAutorepeat: event.get("repeat", 0),
            self.kCGEventSourceUnixProcessID: event.get("pid", 0),
        }[field]

    def _get_flags(self, event):
        if self._flags_error is not None:
            raise self._flags_error
        return event.get("flags", 0)


@unittest.skipUnless(
    _PYNPUT_AVAILABLE and platform.system() == "Darwin", "macOS keycodes (pynput darwin backend)"
)
class MacSuppressionGapTests(unittest.TestCase):
    """#41: character keys, right-hand modifiers and flagsChanged press/release."""

    # macOS virtual keycodes and device-dependent modifier flag bits
    R, Z_QWERTY, Z_QWERTZ, SPACE = 15, 6, 16, 49
    CTRL_L, CTRL_R, SHIFT_L, SHIFT_R = 59, 62, 56, 60
    ALT_L, ALT_R, CMD_L, CMD_R = 58, 61, 55, 54
    BIT = {59: 0x1, 62: 0x2000, 56: 0x2, 60: 0x4, 55: 0x8, 54: 0x10, 58: 0x20, 61: 0x40}

    def setUp(self):
        self.quartz = _FakeQuartz()
        patcher = mock.patch.dict(sys.modules, {"Quartz": self.quartz})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.other_keys = []
        self.held_bits = 0  # modifier flag bits the fake keyboard currently holds

    def _listener(self, hotkey, mode="toggle"):
        listener = HotkeyListener(
            hotkey=hotkey, mode=mode, on_start=lambda: None, on_stop=lambda: None,
            on_other_key=lambda: self.other_keys.append(1),
        )
        self.addCleanup(listener.stop)
        return listener

    def _intercept(self, listener, kind, vk, repeat=0):
        event = {"vk": vk, "repeat": repeat, "flags": self.held_bits}
        return listener._intercept_event(kind, event)

    def _key(self, listener, key, down=True, repeat=0, seen_by_tap=True):
        """A hardware keystroke: pynput callback first, then the intercept."""
        vk = key.value.vk if isinstance(key, keyboard.Key) else key.vk
        (listener._on_press if down else listener._on_release)(key, False)
        if vk in self.BIT:
            self.held_bits = (self.held_bits | self.BIT[vk]) if down else (
                self.held_bits & ~self.BIT[vk]
            )
            kind = self.quartz.kCGEventFlagsChanged
        else:
            kind = self.quartz.kCGEventKeyDown if down else self.quartz.kCGEventKeyUp
        if not seen_by_tap:
            return "lost"
        return self._intercept(listener, kind, vk, repeat)

    @staticmethod
    def _char(char, vk):
        return keyboard.KeyCode.from_char(char, vk=vk)

    def test_ac1_given_ctrl_shift_r_when_r_completes_it_then_down_repeat_and_up_are_swallowed(self):
        listener = self._listener("ctrl+shift+r")
        self.assertIsNotNone(self._key(listener, keyboard.Key.ctrl))
        self.assertIsNotNone(self._key(listener, keyboard.Key.shift))
        r = self._char("R", self.R)
        self.assertIsNone(self._key(listener, r))
        self.assertTrue(listener.is_recording)
        self.assertIsNone(self._key(listener, r, repeat=1))
        self.assertIsNone(self._key(listener, r, down=False))
        self.assertEqual(self.other_keys, [])

    def test_ac1_given_cmd_shift_z_on_qwerty_or_qwertz_when_z_completes_then_its_own_keycode_is_swallowed(self):
        # Without Ctrl, pynput reports the layout's character with its keycode.
        # With Ctrl held it maps letters through a US table instead (see PR #67).
        for vk in (self.Z_QWERTY, self.Z_QWERTZ):
            with self.subTest(vk=vk):
                listener = self._listener("cmd+shift+z")
                self._key(listener, keyboard.Key.cmd)
                self._key(listener, keyboard.Key.shift)
                z = self._char("z", vk)
                self.assertIsNone(self._key(listener, z))
                self.assertIsNone(self._key(listener, z, down=False))
                self._key(listener, keyboard.Key.shift, down=False)
                self._key(listener, keyboard.Key.cmd, down=False)

    def test_ac2_given_ctrl_shift_r_when_plain_r_or_ctrl_r_pressed_then_r_passes(self):
        listener = self._listener("ctrl+shift+r")
        r = self._char("r", self.R)
        self.assertIsNotNone(self._key(listener, r))
        self.assertIsNotNone(self._key(listener, r, down=False))
        self._key(listener, keyboard.Key.ctrl)
        self.assertIsNotNone(self._key(listener, r))
        self.assertIsNotNone(self._key(listener, r, down=False))
        self.assertFalse(listener.is_recording)

    def test_ac3_given_generic_modifiers_when_binding_built_then_both_sides_are_included(self):
        listener = self._listener("ctrl+shift+alt+cmd+space")
        self.assertEqual(
            listener._record.vks,
            {self.CTRL_L, self.CTRL_R, self.SHIFT_L, self.SHIFT_R,
             self.ALT_L, self.ALT_R, self.CMD_L, self.CMD_R, self.SPACE},
        )

    def test_ac3_given_ctrl_space_held_when_right_shift_completes_then_it_is_swallowed(self):
        listener = self._listener("ctrl+shift+space")
        self.assertIsNotNone(self._key(listener, keyboard.Key.ctrl))
        self.assertIsNotNone(self._key(listener, keyboard.Key.space))
        self.assertIsNone(self._key(listener, keyboard.Key.shift_r))
        self.assertTrue(listener.is_recording)
        self.assertIsNone(self._key(listener, keyboard.Key.shift_r, down=False))

    def test_ac3_given_shift_space_held_when_right_ctrl_completes_then_it_is_swallowed(self):
        listener = self._listener("ctrl+shift+space")
        self._key(listener, keyboard.Key.shift)
        self._key(listener, keyboard.Key.space)
        self.assertIsNone(self._key(listener, keyboard.Key.ctrl_r))
        self.assertIsNone(self._key(listener, keyboard.Key.ctrl_r, down=False))

    def test_ac4_given_cmd_r_binding_then_only_the_right_side_is_swallowed(self):
        listener = self._listener("cmd_r", mode="push-to-talk")
        self.assertEqual(listener._record.vks, {self.CMD_R})
        self.assertIsNotNone(self._key(listener, keyboard.Key.cmd_l))
        self.assertIsNotNone(self._key(listener, keyboard.Key.cmd_l, down=False))
        self.assertIsNone(self._key(listener, keyboard.Key.cmd_r))
        self.assertIsNone(self._key(listener, keyboard.Key.cmd_r, down=False))

    def test_ac5_given_a_lost_modifier_release_when_pressed_again_alone_then_it_passes(self):
        listener = self._listener("ctrl+shift+space")
        self._key(listener, keyboard.Key.ctrl)
        self._key(listener, keyboard.Key.space)
        self.assertIsNone(self._key(listener, keyboard.Key.shift_r))
        self._key(listener, keyboard.Key.shift_r, down=False, seen_by_tap=False)
        self._key(listener, keyboard.Key.space, down=False)
        self._key(listener, keyboard.Key.ctrl, down=False)
        self.assertIsNotNone(self._key(listener, keyboard.Key.shift_r))
        self.assertIsNotNone(self._key(listener, keyboard.Key.shift_r, down=False))

    def test_ac5_given_a_lost_modifier_release_when_press_completes_binding_again_then_swallowed(self):
        listener = self._listener("ctrl+shift+space")
        self._key(listener, keyboard.Key.ctrl)
        self._key(listener, keyboard.Key.space)
        self.assertIsNone(self._key(listener, keyboard.Key.shift_r))
        self._key(listener, keyboard.Key.shift_r, down=False, seen_by_tap=False)
        self.assertIsNone(self._key(listener, keyboard.Key.shift_r))
        self.assertIsNone(self._key(listener, keyboard.Key.shift_r, down=False))

    def test_ac5_given_unrelated_binding_active_when_stale_modifier_pressed_then_it_passes(self):
        listener = self._listener("ctrl+shift+space")
        listener.add_binding("undo", "f1", lambda: None)
        self._key(listener, keyboard.Key.ctrl)
        self._key(listener, keyboard.Key.space)
        self._key(listener, keyboard.Key.shift_r)
        self._key(listener, keyboard.Key.shift_r, down=False, seen_by_tap=False)
        self._key(listener, keyboard.Key.space, down=False)
        self._key(listener, keyboard.Key.ctrl, down=False)
        self.assertIsNone(self._key(listener, keyboard.Key.f1))  # undo binding held
        self.assertIsNotNone(self._key(listener, keyboard.Key.shift_r))

    def test_ac5_given_left_shift_held_when_right_shift_released_then_release_is_recognised(self):
        listener = self._listener("ctrl+shift+space")
        self._key(listener, keyboard.Key.shift_l)
        self._key(listener, keyboard.Key.ctrl)
        self._key(listener, keyboard.Key.space)  # completes: Space swallowed
        self._key(listener, keyboard.Key.space, down=False)
        self.assertIsNotNone(self._key(listener, keyboard.Key.shift_r))
        self.assertIsNotNone(self._key(listener, keyboard.Key.shift_r, down=False))
        self.assertNotIn(self.SHIFT_R, listener._suppressed_vks)

    def test_ac6_given_get_flags_raises_then_flags_changed_falls_back_to_release(self):
        for quartz in (_FakeQuartz(flags_error=RuntimeError("boom")), _FakeQuartz(with_flags=False)):
            with self.subTest(quartz=quartz), mock.patch.dict(sys.modules, {"Quartz": quartz}):
                listener = self._listener("ctrl+shift+space")
                self.quartz = quartz
                self._key(listener, keyboard.Key.ctrl)
                self._key(listener, keyboard.Key.space)
                with self.assertLogs("claude_stt.hotkey", level="DEBUG") as logs:
                    # Today's behavior: every flagsChanged counts as a release.
                    self.assertIsNone(self._key(listener, keyboard.Key.shift_r))
                    self.assertIsNone(self._key(listener, keyboard.Key.shift_r, down=False))
                self.assertTrue(any("flags" in line.lower() for line in logs.output))
                self.assertNotIn(self.SHIFT_R, listener._suppressed_vks)

    def test_ac6_given_flags_changed_without_known_bit_then_it_reads_as_release_with_debug_log(self):
        listener = self._listener("ctrl+shift+space")
        caps_lock, fn = 57, 63
        for vk in (caps_lock, fn):
            with self.subTest(vk=vk), self.assertLogs("claude_stt.hotkey", level="DEBUG") as logs:
                self.held_bits = 0xFFFF
                self.assertIsNotNone(self._intercept(listener, self.quartz.kCGEventFlagsChanged, vk))
            self.assertTrue(any(f"flag bit for vk={vk}" in line for line in logs.output))
        self.assertEqual(self.other_keys, [])

    def test_ac7_given_ctrl_shift_space_when_plain_space_pressed_then_it_passes(self):
        listener = self._listener("ctrl+shift+space")
        self.assertIsNotNone(self._key(listener, keyboard.Key.space))
        self.assertIsNotNone(self._key(listener, keyboard.Key.space, down=False))

    def test_ac9_given_modifier_press_with_flag_bit_then_other_key_does_not_fire(self):
        listener = self._listener("ctrl+shift+space")
        for key in (keyboard.Key.shift_r, keyboard.Key.ctrl_r, keyboard.Key.cmd, keyboard.Key.alt_r):
            self._key(listener, key)
            self._key(listener, key, down=False)
        self.assertEqual(self.other_keys, [])


if __name__ == "__main__":
    unittest.main()
