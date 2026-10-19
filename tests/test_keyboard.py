import unittest
from unittest import mock

from claude_stt.config import Config
from claude_stt import keyboard


class KeyboardOutputTests(unittest.TestCase):
    def test_output_falls_back_when_pynput_missing(self):
        original_available = keyboard._PYNPUT_AVAILABLE
        original_clipboard = keyboard._output_via_clipboard
        original_checked = keyboard._injection_checked_at
        original_capable = keyboard._injection_capable
        try:
            keyboard._PYNPUT_AVAILABLE = False
            keyboard._injection_checked_at = None
            keyboard._injection_capable = None
            captured = {}

            def fake_clipboard(text, config):
                captured["text"] = text
                return "clipboard"

            keyboard._output_via_clipboard = fake_clipboard
            config = Config(output_mode="auto")
            result = keyboard.output_text("hello", config=config)
            self.assertTrue(result)
            self.assertEqual(result.mode, "clipboard")
            self.assertEqual(captured["text"], "hello. ")
        finally:
            keyboard._PYNPUT_AVAILABLE = original_available
            keyboard._output_via_clipboard = original_clipboard
            keyboard._injection_checked_at = original_checked
            keyboard._injection_capable = original_capable


class InsertResultTests(unittest.TestCase):
    """output_text reports what reached the app and how (#45)."""

    def setUp(self):
        self.kb = mock.Mock()
        for patcher in (
            mock.patch.object(keyboard, "_PYNPUT_AVAILABLE", True),
            mock.patch.object(keyboard, "get_keyboard", return_value=self.kb),
            mock.patch.object(keyboard, "is_wayland", return_value=False),
            mock.patch.object(keyboard, "play_sound"),
            mock.patch.object(keyboard.time, "sleep"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_ac1_given_injection_when_output_then_result_has_text_and_mode(self):
        result = keyboard.output_text("Hallo Welt", config=Config(output_mode="injection"))
        self.assertEqual(result, keyboard.InsertResult(text="Hallo Welt. ", mode="injection"))
        self.kb.type.assert_called_once_with("Hallo Welt. ")

    def test_ac7_given_plain_clipboard_when_output_then_mode_is_clipboard(self):
        pyperclip = mock.Mock()
        with mock.patch.dict("sys.modules", {"pyperclip": pyperclip}):
            result = keyboard.output_text("Hallo", config=Config(output_mode="clipboard"))
        self.assertEqual(result.mode, "clipboard")
        self.kb.type.assert_not_called()

    def test_ac7_given_paste_without_pynput_when_output_then_mode_is_clipboard(self):
        pyperclip = mock.Mock()
        with mock.patch.dict("sys.modules", {"pyperclip": pyperclip}), \
                mock.patch.object(keyboard, "_PYNPUT_AVAILABLE", False), \
                mock.patch.object(keyboard, "_snapshot_pasteboard", return_value=None):
            result = keyboard.output_text("Hallo", config=Config(output_mode="clipboard_paste"))
        self.assertEqual(result.mode, "clipboard")

    def test_ac13_given_clipboard_paste_when_output_then_paste_restore_and_sound_unchanged(self):
        pyperclip = mock.Mock()
        snapshot = [{"public.utf8-plain-text": b"old"}]
        with mock.patch.dict("sys.modules", {"pyperclip": pyperclip}), \
                mock.patch.object(keyboard, "_snapshot_pasteboard", return_value=snapshot), \
                mock.patch.object(keyboard, "_restore_pasteboard") as restore:
            result = keyboard.output_text(
                "Hallo Welt", config=Config(output_mode="clipboard_paste", sound_effects=True)
            )
        self.assertEqual(result, keyboard.InsertResult(text="Hallo Welt. ", mode="clipboard_paste"))
        pyperclip.copy.assert_called_once_with("Hallo Welt. ")
        self.assertEqual(
            self.kb.mock_calls,
            [
                mock.call.press(keyboard.Key.cmd),
                mock.call.press("v"),
                mock.call.release("v"),
                mock.call.release(keyboard.Key.cmd),
            ],
        )
        restore.assert_called_once_with(snapshot)
        keyboard.play_sound.assert_called_once_with("complete")

    def test_given_clipboard_failure_when_output_then_result_is_falsy(self):
        with mock.patch.dict("sys.modules", {"pyperclip": None}):
            result = keyboard.output_text("Hallo", config=Config(output_mode="clipboard"))
        self.assertFalse(result)

    def test_ac1_given_a_count_when_undoing_then_exactly_that_many_backspaces_are_sent(self):
        self.assertTrue(keyboard.undo_last_insert(12))
        self.assertEqual(self.kb.press.call_args_list, [mock.call(keyboard.Key.backspace)] * 12)
        self.assertEqual(self.kb.release.call_args_list, [mock.call(keyboard.Key.backspace)] * 12)

    def test_given_zero_when_undoing_then_nothing_is_sent(self):
        self.assertFalse(keyboard.undo_last_insert(0))
        self.kb.press.assert_not_called()


if __name__ == "__main__":
    unittest.main()
