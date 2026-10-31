"""#49: the Settings hotkey recorder pauses the daemon's hotkeys."""

import os
import queue
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    from pynput import keyboard
    _PYNPUT_AVAILABLE = True
except Exception:
    keyboard = None
    _PYNPUT_AVAILABLE = False

from claude_stt import hotkey_pause
from claude_stt.hotkey import HotkeyListener


@unittest.skipUnless(_PYNPUT_AVAILABLE, "pynput unavailable in this environment")
class HotkeyPauseTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config_dir = Path(self._tmp.name)
        self._env = mock.patch.dict(os.environ, {"LOCAL_STT_CONFIG_DIR": str(self.config_dir)})
        self._env.start()
        self.events: "queue.Queue[str]" = queue.Queue()
        self.listener = HotkeyListener(
            hotkey="f1",
            mode="toggle",
            on_start=lambda: self.events.put("start"),
            on_stop=lambda: self.events.put("stop"),
        )
        self.pause_file = self.config_dir / hotkey_pause.PAUSE_FILE

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def press_ctrl_f1(self):
        self.listener._on_press(keyboard.Key.ctrl)
        self.listener._on_press(keyboard.Key.f1)

    def test_ac1_given_recorder_active_when_ctrl_f1_pressed_then_record_hotkey_does_not_fire(self):
        self.pause_file.touch()
        self.press_ctrl_f1()
        time.sleep(0.05)
        self.assertTrue(self.events.empty())
        self.assertFalse(any(b.active for b in self.listener._bindings))

    def test_ac2_given_stale_pause_file_when_hotkey_pressed_then_it_fires(self):
        self.pause_file.touch()
        old = time.time() - hotkey_pause.MAX_AGE_S - 1
        os.utime(self.pause_file, (old, old))
        self.listener._on_press(keyboard.Key.f1)
        self.assertEqual(self.events.get(timeout=0.5), "start")

    def test_ac3_given_no_pause_file_when_ctrl_f1_pressed_then_f1_still_fires(self):
        self.press_ctrl_f1()
        self.assertEqual(self.events.get(timeout=0.5), "start")

    def test_given_key_held_through_pause_end_when_it_repeats_then_hotkey_does_not_fire(self):
        self.pause_file.touch()
        self.press_ctrl_f1()
        self.pause_file.unlink()
        self.listener._on_press(keyboard.Key.f1)  # key repeat
        time.sleep(0.05)
        self.assertTrue(self.events.empty())
        self.listener._on_release(keyboard.Key.f1)
        self.listener._on_release(keyboard.Key.ctrl)
        self.listener._on_press(keyboard.Key.f1)
        self.assertEqual(self.events.get(timeout=0.5), "start")


if __name__ == "__main__":
    unittest.main()
