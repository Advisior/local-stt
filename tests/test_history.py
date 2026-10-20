import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from claude_stt import history


def _entry(text: str, timestamp: str = "2026-10-20T10:00:00") -> dict:
    return {"timestamp": timestamp, "text": text, "duration_s": 1.0, "db": -30.0, "words": len(text.split())}


class _ConfigDirTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config_dir = Path(self._tmp.name)
        self.history_path = self.config_dir / history.HISTORY_FILE

    def tearDown(self):
        self._tmp.cleanup()

    def write_lines(self, entries):
        self.history_path.write_text("".join(json.dumps(e) + "\n" for e in entries))

    def read_entries(self):
        return [json.loads(line) for line in self.history_path.read_text().splitlines() if line.strip()]


class AppendTests(_ConfigDirTestCase):
    def test_ac14_given_private_mode_off_when_appending_then_entry_stored_as_json_line(self):
        history.append_entry(_entry("first"), config_dir=self.config_dir)
        history.append_entry(_entry("second"), config_dir=self.config_dir)
        content = self.history_path.read_text()
        self.assertTrue(content.endswith("\n"))
        self.assertEqual([e["text"] for e in self.read_entries()], ["first", "second"])
        self.assertEqual(content.splitlines()[0], json.dumps(_entry("first")))

    def test_ac14_given_100_entries_when_appending_then_last_100_are_kept(self):
        self.write_lines([_entry(f"e{i}") for i in range(100)])
        history.append_entry(_entry("new"), config_dir=self.config_dir)
        texts = [e["text"] for e in self.read_entries()]
        self.assertEqual(len(texts), 100)
        self.assertEqual(texts[0], "e1")
        self.assertEqual(texts[-1], "new")

    def test_ac14_given_no_leftover_temp_files_when_appending_then_dir_holds_only_history_and_lock(self):
        history.append_entry(_entry("x"), config_dir=self.config_dir)
        names = sorted(p.name for p in self.config_dir.iterdir())
        self.assertEqual(names, [history.HISTORY_FILE, history.LOCK_FILE])

    def test_ac14_given_missing_config_dir_when_appending_then_dir_is_created(self):
        nested = self.config_dir / "sub"
        history.append_entry(_entry("x"), config_dir=nested)
        self.assertTrue((nested / history.HISTORY_FILE).exists())


class DeleteTests(_ConfigDirTestCase):
    def test_ac1_given_three_entries_when_deleting_middle_then_others_keep_order(self):
        self.write_lines([_entry("a", "t1"), _entry("b", "t2"), _entry("c", "t3")])
        self.assertTrue(history.delete_entry("t2", "b", config_dir=self.config_dir))
        self.assertEqual([e["text"] for e in self.read_entries()], ["a", "c"])

    def test_ac2_given_duplicate_entries_when_deleting_one_then_only_one_is_removed(self):
        self.write_lines([_entry("same", "t1"), _entry("same", "t1"), _entry("other", "t2")])
        self.assertTrue(history.delete_entry("t1", "same", config_dir=self.config_dir))
        self.assertEqual([e["text"] for e in self.read_entries()], ["same", "other"])

    def test_ac4_given_entry_not_in_file_when_deleting_then_file_is_unchanged(self):
        self.write_lines([_entry("a", "t1")])
        before = self.history_path.read_bytes()
        self.assertFalse(history.delete_entry("t9", "gone", config_dir=self.config_dir))
        self.assertEqual(self.history_path.read_bytes(), before)

    def test_ac4_given_no_history_file_when_deleting_then_nothing_happens(self):
        self.assertFalse(history.delete_entry("t1", "a", config_dir=self.config_dir))
        self.assertFalse(self.history_path.exists())

    def test_ac1_given_last_entry_when_deleting_then_file_is_empty(self):
        self.write_lines([_entry("a", "t1")])
        self.assertTrue(history.delete_entry("t1", "a", config_dir=self.config_dir))
        self.assertEqual(self.read_entries(), [])

    def test_ac1_given_malformed_line_when_deleting_then_other_lines_are_kept_verbatim(self):
        self.history_path.write_text("not json\n" + json.dumps(_entry("a", "t1")) + "\n")
        self.assertTrue(history.delete_entry("t1", "a", config_dir=self.config_dir))
        self.assertEqual(self.history_path.read_text(), "not json\n")


class InvalidBytesTests(_ConfigDirTestCase):
    BAD = b"\xff\xfe broken\n"

    def test_ac14_given_invalid_utf8_line_when_appending_then_entry_is_added_and_line_kept(self):
        self.history_path.write_bytes(self.BAD + (json.dumps(_entry("a", "t1")) + "\n").encode())
        history.append_entry(_entry("b", "t2"), config_dir=self.config_dir)
        raw = self.history_path.read_bytes()
        self.assertTrue(raw.startswith(self.BAD))
        self.assertTrue(raw.endswith((json.dumps(_entry("b", "t2")) + "\n").encode()))

    def test_ac1_given_invalid_utf8_line_when_deleting_then_match_removed_and_line_kept(self):
        self.history_path.write_bytes(self.BAD + (json.dumps(_entry("a", "t1")) + "\n").encode())
        self.assertTrue(history.delete_entry("t1", "a", config_dir=self.config_dir))
        self.assertEqual(self.history_path.read_bytes(), self.BAD)


_CHILD_APPEND = """
import sys
from pathlib import Path
from claude_stt import history
d = Path(sys.argv[1])
for i in range(40):
    history.append_entry({"timestamp": "new", "text": f"new{i}"}, config_dir=d)
"""

_CHILD_DELETE = """
import sys
from pathlib import Path
from claude_stt import history
d = Path(sys.argv[1])
for i in range(0, 60, 2):
    assert history.delete_entry("old", f"old{i}", config_dir=d)
"""


class ConcurrencyTests(_ConfigDirTestCase):
    def test_ac3_given_lock_held_when_appending_then_append_waits_for_release(self):
        done = threading.Event()

        def append():
            history.append_entry(_entry("late"), config_dir=self.config_dir)
            done.set()

        with history.history_lock(self.config_dir):
            worker = threading.Thread(target=append)
            worker.start()
            time.sleep(0.3)
            self.assertFalse(done.is_set(), "append must block while another writer holds history.lock")
        worker.join(timeout=5)
        self.assertTrue(done.is_set())
        self.assertEqual([e["text"] for e in self.read_entries()], ["late"])

    def test_ac3_given_concurrent_append_and_delete_processes_then_both_effects_persist(self):
        self.write_lines([{"timestamp": "old", "text": f"old{i}"} for i in range(60)])
        procs = [
            subprocess.Popen([sys.executable, "-c", code, str(self.config_dir)])
            for code in (_CHILD_APPEND, _CHILD_DELETE)
        ]
        for proc in procs:
            self.assertEqual(proc.wait(timeout=60), 0)
        texts = [e["text"] for e in self.read_entries()]
        self.assertEqual(texts.count("old0"), 0)
        self.assertEqual([t for t in texts if t.startswith("old")], [f"old{i}" for i in range(1, 60, 2)])
        self.assertEqual([t for t in texts if t.startswith("new")], [f"new{i}" for i in range(40)])


class PrivateModeTests(_ConfigDirTestCase):
    now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)

    def write_state(self, raw: str):
        (self.config_dir / history.PRIVATE_MODE_FILE).write_text(raw)

    def active(self):
        return history.private_mode_active(now=self.now, config_dir=self.config_dir)

    def test_ac11_given_no_state_file_then_private_mode_is_off(self):
        self.assertFalse(self.active())

    def test_ac11_given_until_null_then_private_mode_is_on(self):
        self.write_state('{"until": null}')
        self.assertTrue(self.active())

    def test_ac11_given_future_until_then_private_mode_stays_on_after_restart(self):
        self.write_state(json.dumps({"until": (self.now + timedelta(minutes=10)).isoformat()}))
        self.assertTrue(self.active())
        self.write_state('{"until": "2026-10-20T12:10:00Z"}')
        self.assertTrue(self.active())

    def test_ac10_given_until_elapsed_then_private_mode_is_off(self):
        self.write_state('{"until": "2026-10-20T11:59:59Z"}')
        self.assertFalse(self.active())

    def test_ac10_given_until_equal_now_then_private_mode_is_off(self):
        self.write_state('{"until": "2026-10-20T12:00:00Z"}')
        self.assertFalse(self.active())

    def test_ac12_given_malformed_state_then_private_mode_is_on_and_warning_has_no_text(self):
        cases = [
            "not json",
            "",
            "[]",
            "{}",
            '{"until": 5}',
            '{"until": "tomorrow"}',
            '{"until": "2026-10-20T13:00:00"}',  # no timezone, not UTC
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                self.write_state(raw)
                with self.assertLogs("claude_stt.history", level="WARNING") as logs:
                    self.assertTrue(self.active())
                self.assertTrue(all("private_mode.json" in line for line in logs.output))

    def test_ac12_given_state_with_invalid_utf8_then_private_mode_is_on_and_warning_has_no_text(self):
        (self.config_dir / history.PRIVATE_MODE_FILE).write_bytes(b"\xff\xfe{")
        with self.assertLogs("claude_stt.history", level="WARNING") as logs:
            self.assertTrue(self.active())
        self.assertTrue(all("private_mode.json" in line for line in logs.output))

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), "needs POSIX permissions")
    def test_ac12_given_unreadable_state_then_private_mode_is_on(self):
        path = self.config_dir / history.PRIVATE_MODE_FILE
        path.write_text('{"until": null}')
        path.chmod(0)
        try:
            with self.assertLogs("claude_stt.history", level="WARNING"):
                self.assertTrue(self.active())
        finally:
            path.chmod(0o600)


if __name__ == "__main__":
    unittest.main()
