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
                return True

            keyboard._output_via_clipboard = fake_clipboard
            config = Config(output_mode="auto")
            result = keyboard.output_text("hello", config=config)
            self.assertTrue(result)
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


if __name__ == "__main__":
    unittest.main()
