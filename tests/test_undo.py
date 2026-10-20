import unittest

from claude_stt.keyboard import InsertResult
from claude_stt.undo import NOTHING_TO_UNDO, TOO_LONG_TO_UNDO, UndoTracker


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class UndoTrackerTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.app = "com.mitchellh.ghostty"
        self.tracker = UndoTracker(
            window_seconds=60,
            max_chars=400,
            clock=self.clock,
            frontmost_app=lambda: self.app,
        )

    def _insert(self, text="Hallo Welt. ", mode="clipboard_paste"):
        self.tracker.record(InsertResult(text=text, mode=mode), self.tracker.begin_insert())

    def _assert_refused(self, decision, hint=NOTHING_TO_UNDO):
        self.assertEqual(decision.action, "refuse")
        self.assertEqual(decision.hint, hint)
        self.assertEqual(decision.count, 0)
        self.assertTrue(decision.reason)

    def test_ac1_given_a_fresh_paste_when_undo_then_one_backspace_per_character(self):
        self._insert("Hallo Welt. ")
        decision = self.tracker.check(busy=False)
        self.assertEqual(decision.action, "send")
        self.assertEqual(decision.count, 12)  # includes the trailing space

    def test_ac1_given_an_injected_insert_when_undo_then_it_is_undoable(self):
        self._insert("Okay. ", mode="injection")
        self.assertEqual(self.tracker.check(busy=False).count, 6)

    def test_ac1_given_umlauts_when_counting_then_each_is_one_character(self):
        self._insert("Grüße aus Köln. ")
        self.assertEqual(self.tracker.check(busy=False).count, 16)

    def test_ac1_given_decomposed_umlaut_when_counting_then_nfc_code_points_count(self):
        self._insert("Grüße. ")  # u + combining diaeresis composes to ü
        self.assertEqual(self.tracker.check(busy=False).count, 7)

    def test_ac2_given_an_undone_insert_when_undo_again_then_nothing_to_undo(self):
        self._insert()
        self.assertEqual(self.tracker.check(busy=False).action, "send")
        self._assert_refused(self.tracker.check(busy=False))

    def test_ac3_given_another_frontmost_app_when_undo_then_nothing_to_undo(self):
        self._insert()
        self.app = "com.apple.TextEdit"
        self._assert_refused(self.tracker.check(busy=False))

    def test_ac3_given_unknown_frontmost_app_when_undo_then_nothing_to_undo(self):
        self.app = None
        self._insert()
        self._assert_refused(self.tracker.check(busy=False))

    def test_ac3_given_an_app_switch_during_the_paste_when_undo_in_new_app_then_nothing(self):
        start = self.tracker.begin_insert()
        self.app = "com.apple.TextEdit"  # user switches while paste and restore run
        self.tracker.record(InsertResult(text="Hallo. ", mode="clipboard_paste"), start)
        self._assert_refused(self.tracker.check(busy=False))

    def test_ac4_given_an_insert_older_than_the_window_when_undo_then_nothing_to_undo(self):
        self._insert()
        self.clock.now += 60.5
        self._assert_refused(self.tracker.check(busy=False))

    def test_ac4_given_an_insert_inside_the_window_when_undo_then_it_is_sent(self):
        self._insert()
        self.clock.now += 59.5
        self.assertEqual(self.tracker.check(busy=False).action, "send")

    def test_ac5_given_a_key_after_the_insert_when_undo_then_nothing_to_undo(self):
        self._insert()
        self.tracker.invalidate()
        self._assert_refused(self.tracker.check(busy=False))

    def test_ac5_given_a_key_during_the_paste_when_recorded_then_insert_is_invalid(self):
        start = self.tracker.begin_insert()
        self.tracker.invalidate()  # user typed while the paste was in flight
        self.tracker.record(InsertResult(text="Hallo. ", mode="clipboard_paste"), start)
        self._assert_refused(self.tracker.check(busy=False))

    def test_ac5_given_a_key_before_the_insert_when_undo_then_it_still_works(self):
        self.tracker.invalidate()
        self._insert()
        self.assertEqual(self.tracker.check(busy=False).action, "send")

    def test_ac6_given_text_longer_than_max_chars_when_undo_then_too_long(self):
        self._insert("a" * 400 + " ")
        self._assert_refused(self.tracker.check(busy=False), TOO_LONG_TO_UNDO)

    def test_ac6_given_text_exactly_max_chars_when_undo_then_it_is_sent(self):
        self._insert("a" * 399 + " ")
        self.assertEqual(self.tracker.check(busy=False).count, 400)

    def test_ac6_given_a_line_break_when_undo_then_too_long(self):
        for text in ("Erster Absatz.\n\nZweiter. ", "Zeile\rzwei. "):
            with self.subTest(text=text):
                self._insert(text)
                self._assert_refused(self.tracker.check(busy=False), TOO_LONG_TO_UNDO)

    def test_ac6_given_units_one_backspace_may_not_remove_when_undo_then_nothing(self):
        for text in ("Super \U0001F44D. ", "Team ‍ ok. ", "Café́. "):
            with self.subTest(text=text):
                self._insert(text)
                self._assert_refused(self.tracker.check(busy=False))

    def test_ac6_given_a_variation_selector_when_undo_then_nothing_to_undo(self):
        self._insert("heart \u2764\ufe0f. ")
        self._assert_refused(self.tracker.check(busy=False))

    def test_ac7_given_no_insert_since_start_when_undo_then_nothing_to_undo(self):
        self._assert_refused(self.tracker.check(busy=False))

    def test_ac7_given_plain_clipboard_mode_when_undo_then_nothing_to_undo(self):
        self._insert(mode="clipboard")
        self._assert_refused(self.tracker.check(busy=False))

    def test_ac7_given_a_clipboard_insert_after_a_paste_when_undo_then_old_paste_is_gone(self):
        self._insert(mode="clipboard_paste")
        self._insert(mode="clipboard")
        self._assert_refused(self.tracker.check(busy=False))

    def test_ac8_given_recording_or_transcribing_when_undo_then_it_is_ignored(self):
        self._insert()
        decision = self.tracker.check(busy=True)
        self.assertEqual(decision.action, "ignore")
        self.assertEqual(decision.count, 0)
        self.assertEqual(self.tracker.check(busy=False).action, "send")  # still undoable

    def test_ac2_ac4_order_given_an_undone_and_expired_insert_then_still_nothing(self):
        self._insert()
        self.tracker.check(busy=False)
        self.clock.now += 120
        self._assert_refused(self.tracker.check(busy=False))


if __name__ == "__main__":
    unittest.main()
