import sys
import types
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

            def fake_clipboard(text, config, private=False):
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


class _FakeItem:
    def __init__(self):
        self.values = {}

    @classmethod
    def alloc(cls):
        return cls()

    def init(self):
        return self

    def setString_forType_(self, value, kind):
        self.values[str(kind)] = value
        return True


class _FakePasteboard:
    def __init__(self, write_ok=True):
        self.written = []
        self.write_ok = write_ok

    def pasteboardItems(self):
        return []

    def clearContents(self):
        self.written = []

    def writeObjects_(self, items):
        self.written = list(items)
        return self.write_ok


def _fake_appkit(pasteboard):
    module = types.ModuleType("AppKit")
    module.NSPasteboard = types.SimpleNamespace(generalPasteboard=lambda: pasteboard)
    module.NSPasteboardItem = _FakeItem
    module.NSPasteboardTypeString = "public.utf8-plain-text"
    return module


class PrivateClipboardTests(unittest.TestCase):
    def setUp(self):
        self.pasteboard = _FakePasteboard()
        self.pyperclip = mock.MagicMock()
        patches = [
            mock.patch.dict(sys.modules, {"AppKit": _fake_appkit(self.pasteboard), "pyperclip": self.pyperclip}),
            mock.patch.object(keyboard, "_IS_MACOS", True),
            mock.patch.object(keyboard, "_PYNPUT_AVAILABLE", False),
            mock.patch.object(keyboard.time, "sleep"),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def assert_concealed_write(self, text):
        self.assertEqual(len(self.pasteboard.written), 1)
        values = self.pasteboard.written[0].values
        self.assertEqual(values["public.utf8-plain-text"], text)
        self.assertIn("org.nspasteboard.ConcealedType", values)
        self.assertIn("org.nspasteboard.TransientType", values)
        self.pyperclip.copy.assert_not_called()

    def test_ac8_given_private_mode_when_output_mode_clipboard_then_write_is_concealed_and_transient(self):
        config = Config(output_mode="clipboard", sound_effects=False)
        self.assertTrue(keyboard.output_text("secret", config=config, private=True))
        self.assert_concealed_write("secret. ")

    def test_ac8_given_private_mode_when_output_mode_clipboard_paste_then_write_is_concealed_and_transient(self):
        config = Config(output_mode="clipboard_paste", sound_effects=False)
        self.assertTrue(keyboard.output_text("secret", config=config, private=True))
        self.assert_concealed_write("secret. ")

    def test_ac15_given_private_mode_when_clipboard_paste_with_keystroke_then_insert_is_undoable(self):
        kb = mock.Mock()
        with mock.patch.object(keyboard, "_PYNPUT_AVAILABLE", True), \
                mock.patch.object(keyboard, "Key", keyboard.Key or mock.Mock(name="Key")), \
                mock.patch.object(keyboard, "get_keyboard", return_value=kb):
            result = keyboard.output_text(
                "secret", config=Config(output_mode="clipboard_paste", sound_effects=False), private=True
            )
        self.assertEqual(result, keyboard.InsertResult(text="secret. ", mode="clipboard_paste"))
        self.assertIn(result.mode, keyboard.INSERT_MODES)
        self.assert_concealed_write("secret. ")

    def test_ac8_given_private_mode_when_concealed_write_fails_then_text_never_reaches_plain_clipboard(self):
        self.pasteboard.write_ok = False
        config = Config(output_mode="clipboard", sound_effects=False)
        self.assertFalse(keyboard.output_text("secret", config=config, private=True))
        self.pyperclip.copy.assert_not_called()

    def test_ac8_given_private_mode_off_when_output_mode_clipboard_then_plain_copy_is_unchanged(self):
        config = Config(output_mode="clipboard", sound_effects=False)
        self.assertTrue(keyboard.output_text("hello", config=config))
        self.pyperclip.copy.assert_called_once_with("hello. ")
        self.assertEqual(self.pasteboard.written, [])

    def test_ac8_given_private_mode_off_macos_when_clipboard_paste_then_plain_copy_is_unchanged(self):
        config = Config(output_mode="clipboard_paste", sound_effects=False)
        self.assertTrue(keyboard.output_text("hello", config=config))
        self.pyperclip.copy.assert_called_once_with("hello. ")

    def test_ac8_given_non_macos_when_private_then_plain_copy_is_unchanged(self):
        with mock.patch.object(keyboard, "_IS_MACOS", False):
            config = Config(output_mode="clipboard", sound_effects=False)
            self.assertTrue(keyboard.output_text("hello", config=config, private=True))
        self.pyperclip.copy.assert_called_once_with("hello. ")

class InsertResultTests(unittest.TestCase):
    """output_text reports what reached the app and how (#45)."""

    def setUp(self):
        self.kb = mock.Mock()
        for patcher in (
            mock.patch.object(keyboard, "_PYNPUT_AVAILABLE", True),
            # headless Linux CI has no pynput: Key is None there
            mock.patch.object(keyboard, "Key", keyboard.Key or mock.Mock(name="Key")),
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
