"""Pure HUD logic for the recording overlay (#60). No AppKit needed."""

import unittest

from claude_stt import overlay_model as m


class FormatTests(unittest.TestCase):
    def test_elapsed_is_minutes_and_two_digit_seconds(self):
        self.assertEqual(m.format_elapsed(0), "0:00")
        self.assertEqual(m.format_elapsed(7.9), "0:07")
        self.assertEqual(m.format_elapsed(65), "1:05")
        self.assertEqual(m.format_elapsed(-3), "0:00")

    def test_ac6_done_text_counts_words_with_singular(self):
        self.assertEqual(m.done_text(18, "injection"), "Inserted 18 words")
        self.assertEqual(m.done_text(1, "clipboard_paste"), "Inserted 1 word")
        self.assertEqual(m.done_text(0, ""), "Inserted 0 words")

    def test_ac6_clipboard_only_mode_says_copied(self):
        self.assertEqual(m.done_text(3, "clipboard"), "Copied 3 words")

    def test_ac10_texts_use_the_ellipsis_character(self):
        self.assertEqual(m.TRANSCRIBING_TEXT, "Transcribing…")
        self.assertNotIn("...", m.TRANSCRIBING_TEXT)


class ParseCommandTests(unittest.TestCase):
    def test_ac13_existing_commands_still_parse(self):
        self.assertEqual(m.parse_command("RECORDING"), m.Command("RECORDING", ()))
        self.assertEqual(m.parse_command("TRANSCRIBING"), m.Command("TRANSCRIBING", ()))
        self.assertEqual(m.parse_command("DONE 12"), m.Command("DONE", ("12",)))
        self.assertEqual(m.parse_command("DONE"), m.Command("DONE", ()))
        self.assertEqual(m.parse_command("CANCEL"), m.Command("CANCEL", ()))
        self.assertEqual(m.parse_command("QUIT"), m.Command("QUIT", ()))

    def test_hint_keeps_its_whole_text(self):
        self.assertEqual(
            m.parse_command("HINT No microphone input. Check it."),
            m.Command("HINT", ("No microphone input. Check it.",)),
        )

    def test_new_arguments_parse(self):
        self.assertEqual(m.parse_command("RECORDING PRIVATE"), m.Command("RECORDING", ("PRIVATE",)))
        self.assertEqual(m.parse_command("DONE 3 clipboard"), m.Command("DONE", ("3", "clipboard")))
        self.assertEqual(m.parse_command("LEVEL 0.5"), m.Command("LEVEL", ("0.5",)))

    def test_blank_and_unknown_lines_are_ignored(self):
        self.assertIsNone(m.parse_command(""))
        self.assertIsNone(m.parse_command("   \n"))
        self.assertIsNone(m.parse_command("BOGUS 1"))


class ApplyCommandTests(unittest.TestCase):
    def test_ac4_recording_private_sets_the_private_flag(self):
        state = m.apply(m.HudState(), m.parse_command("RECORDING PRIVATE"), now=10.0)
        self.assertEqual(state.kind, m.RECORDING)
        self.assertTrue(state.private)
        self.assertEqual(state.started_at, 10.0)

    def test_recording_resets_levels_and_private(self):
        state = m.HudState(kind=m.DONE, private=True, levels=(0.4, 0.9))
        state = m.apply(state, m.parse_command("RECORDING"), now=1.0)
        self.assertFalse(state.private)
        self.assertEqual(state.levels, ())

    def test_level_is_clamped_and_kept_to_the_meter_length(self):
        state = m.apply(m.HudState(), m.parse_command("RECORDING"), now=0.0)
        for value in ["0.2", "1.7", "-1", "nan", "abc"] + ["0.5"] * 30:
            state = m.apply(state, m.parse_command(f"LEVEL {value}"), now=0.0)
        self.assertEqual(len(state.levels), m.METER_BARS)
        self.assertTrue(all(0.0 <= v <= 1.0 for v in state.levels))

    def test_level_outside_recording_is_ignored(self):
        state = m.apply(m.HudState(kind=m.TRANSCRIBING), m.parse_command("LEVEL 0.5"), now=0.0)
        self.assertEqual(state.levels, ())

    def test_level_clamp_values(self):
        state = m.apply(m.HudState(kind=m.RECORDING), m.parse_command("LEVEL 1.7"), now=0.0)
        state = m.apply(state, m.parse_command("LEVEL -1"), now=0.0)
        self.assertEqual(state.levels, (1.0, 0.0))

    def test_ac5_transcribing_keeps_private_flag(self):
        state = m.apply(m.HudState(kind=m.RECORDING, private=True), m.parse_command("TRANSCRIBING"), now=0.0)
        self.assertEqual(state.kind, m.TRANSCRIBING)
        self.assertEqual(state.text, "Transcribing…")

    def test_ac6_done_with_count_and_mode(self):
        state = m.apply(m.HudState(), m.parse_command("DONE 3 clipboard"), now=0.0)
        self.assertEqual((state.kind, state.text), (m.DONE, "Copied 3 words"))
        state = m.apply(m.HudState(), m.parse_command("DONE x"), now=0.0)
        self.assertEqual(state.text, "Inserted 0 words")

    def test_hint_and_cancel(self):
        state = m.apply(m.HudState(), m.parse_command("HINT Nothing to undo"), now=0.0)
        self.assertEqual((state.kind, state.text), (m.HINT, "Nothing to undo"))
        state = m.apply(state, m.parse_command("CANCEL"), now=0.0)
        self.assertEqual(state.kind, m.HIDDEN)


class ItemsTests(unittest.TestCase):
    """What the capsule shows per state, left to right."""

    def kinds(self, state, reduce_motion=False, now=7.0):
        return [item.kind for item in m.hud_items(state, reduce_motion=reduce_motion, now=now)]

    def test_ac2_recording_shows_dot_meter_time_and_esc(self):
        state = m.HudState(kind=m.RECORDING, started_at=0.0)
        self.assertEqual(self.kinds(state), ["dot", "meter", "time", "key"])
        items = m.hud_items(state, reduce_motion=False, now=7.2)
        self.assertEqual(items[2].text, "0:07")
        self.assertEqual(items[3].text, "esc")

    def test_ac4_private_recording_adds_eye_slash_after_the_dot(self):
        state = m.HudState(kind=m.RECORDING, private=True, started_at=0.0)
        items = m.hud_items(state, reduce_motion=False, now=1.0)
        self.assertEqual([i.kind for i in items], ["dot", "symbol", "meter", "time", "key"])
        self.assertEqual(items[1].symbol, "eye.slash")

    def test_ac3_reduce_motion_swaps_meter_for_static_mic_and_listening(self):
        state = m.HudState(kind=m.RECORDING, started_at=0.0)
        items = m.hud_items(state, reduce_motion=True, now=7.0)
        self.assertEqual([i.kind for i in items], ["dot", "symbol", "text", "time", "key"])
        self.assertEqual(items[1].symbol, "mic.fill")
        self.assertEqual(items[2].text, "Listening")
        self.assertNotIn("meter", [i.kind for i in items])

    def test_ac5_transcribing_spinner_or_static_symbol(self):
        state = m.HudState(kind=m.TRANSCRIBING, text=m.TRANSCRIBING_TEXT)
        self.assertEqual(self.kinds(state), ["spinner", "text"])
        items = m.hud_items(state, reduce_motion=True, now=0.0)
        self.assertEqual([i.kind for i in items], ["symbol", "text"])
        self.assertEqual(items[0].symbol, "ellipsis.circle")

    def test_ac6_done_shows_checkmark_and_text(self):
        state = m.HudState(kind=m.DONE, text="Inserted 2 words")
        items = m.hud_items(state, reduce_motion=False, now=0.0)
        self.assertEqual([(i.kind, i.symbol or i.text) for i in items],
                         [("symbol", "checkmark.circle.fill"), ("text", "Inserted 2 words")])

    def test_hint_shows_warning_symbol(self):
        items = m.hud_items(m.HudState(kind=m.HINT, text="Nothing to undo"), reduce_motion=False, now=0.0)
        self.assertEqual(items[0].symbol, "exclamationmark.triangle.fill")

    def test_hidden_has_no_items(self):
        self.assertEqual(m.hud_items(m.HudState(), reduce_motion=False, now=0.0), [])

    def test_ac12_every_item_has_a_voiceover_label_or_is_decorative(self):
        state = m.HudState(kind=m.RECORDING, private=True, started_at=0.0)
        labels = [i.label for i in m.hud_items(state, reduce_motion=False, now=65.0)]
        self.assertEqual(labels, ["Recording", "Private mode", "Audio level",
                                  "1 minute 5 seconds", "Press Escape to cancel"])


class AnnouncementTests(unittest.TestCase):
    def test_ac12_announcements_per_state(self):
        self.assertEqual(m.announcement(m.HudState(kind=m.RECORDING)), "Recording")
        self.assertEqual(m.announcement(m.HudState(kind=m.RECORDING, private=True)),
                         "Recording, private mode")
        self.assertEqual(m.announcement(m.HudState(kind=m.TRANSCRIBING, text="Transcribing…")),
                         "Transcribing")
        self.assertEqual(m.announcement(m.HudState(kind=m.DONE, text="Inserted 2 words")),
                         "Inserted 2 words")
        self.assertEqual(m.announcement(m.HudState(kind=m.HINT, text="Nothing to undo")),
                         "Nothing to undo")
        self.assertIsNone(m.announcement(m.HudState()))

    def test_spoken_duration(self):
        self.assertEqual(m.spoken_duration(1), "1 second")
        self.assertEqual(m.spoken_duration(7), "7 seconds")
        self.assertEqual(m.spoken_duration(60), "1 minute")
        self.assertEqual(m.spoken_duration(125), "2 minutes 5 seconds")


class LayoutTests(unittest.TestCase):
    def test_ac10_capsule_width_fits_content(self):
        origins, width = m.layout([8, 60, 30], padding=14, spacing=10)
        self.assertEqual(origins, [14, 32, 102])
        self.assertEqual(width, 14 + 8 + 10 + 60 + 10 + 30 + 14)

    def test_long_hint_is_not_truncated_but_capped_by_the_screen(self):
        _, width = m.layout([16, 900], padding=14, spacing=10, max_width=600)
        self.assertEqual(width, 600)
        _, width = m.layout([16, 200], padding=14, spacing=10, max_width=600)
        self.assertEqual(width, 254)

    def test_ac10_a_wrapped_hint_grows_the_capsule_instead_of_truncating(self):
        self.assertEqual(m.capsule_height(16, base=36, vpad=9), 36)
        self.assertEqual(m.capsule_height(34, base=36, vpad=9), 52)

    def test_empty_layout(self):
        self.assertEqual(m.layout([], padding=14, spacing=10), ([], 28))

    def test_ac1_capsule_sits_bottom_center_of_the_visible_frame(self):
        x, y = m.capsule_origin((100, 80, 1440, 860), width=200, height=36, margin=22)
        self.assertEqual((x, y), (100 + (1440 - 200) / 2, 80 + 22))

    def test_meter_bar_heights(self):
        heights = m.bar_heights((0.0, 0.5, 1.0), bars=5, min_h=3, max_h=16)
        self.assertEqual(len(heights), 5)
        self.assertEqual(heights[:2], [3, 3])  # padded with silence on the left
        self.assertEqual(heights[-1], 16)
        self.assertEqual(heights[-3], 3)
        self.assertTrue(3 < heights[-2] < 16)


if __name__ == "__main__":
    unittest.main()
