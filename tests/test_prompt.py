import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from claude_stt.config import Config
from claude_stt.engine_factory import build_engine
from claude_stt.prompt import WHISPER_PROMPT_TOKENS, build_prompt, effective_prompt


def words(text: str) -> int:
    """Test token counter: one token per whitespace-separated word."""
    return len(text.split())


class BuildPromptTests(unittest.TestCase):
    def test_given_only_a_hint_then_the_prompt_is_the_hint_unchanged(self):
        result = build_prompt("Gesprochener Text auf Deutsch.", [], count_tokens=words)
        self.assertEqual(result.text, "Gesprochener Text auf Deutsch.")
        self.assertEqual(result.dropped, [])

    def test_given_hint_and_vocabulary_then_hint_comes_first_and_terms_follow(self):
        result = build_prompt("Deutsch.", ["Advisior", "Cotedo"], count_tokens=words)
        self.assertEqual(result.text, "Deutsch. Advisior, Cotedo")
        self.assertEqual(result.dropped, [])

    def test_given_only_vocabulary_then_the_prompt_lists_the_terms(self):
        result = build_prompt(None, ["Advisior", "Cotedo"], count_tokens=words)
        self.assertEqual(result.text, "Advisior, Cotedo")

    def test_given_nothing_then_there_is_no_prompt(self):
        self.assertIsNone(build_prompt("", [], count_tokens=words).text)
        self.assertIsNone(build_prompt(None, None, count_tokens=words).text)

    def test_given_too_many_terms_then_later_terms_are_dropped_and_the_hint_stays(self):
        result = build_prompt("a b", ["t1", "t2", "t3", "t4"], count_tokens=words, budget=4)
        self.assertEqual(result.text, "a b t1, t2")
        self.assertFalse(result.hint_over_budget)
        self.assertEqual(result.dropped, ["t3", "t4"])
        self.assertLessEqual(words(result.text), 4)

    def test_dropping_keeps_the_order_and_stops_at_the_first_term_that_does_not_fit(self):
        def chars(text: str) -> int:
            return len(text)

        result = build_prompt(None, ["aaaa", "bbbbbbbbbb", "c"], count_tokens=chars, budget=8)
        self.assertEqual(result.text, "aaaa")
        self.assertEqual(result.dropped, ["bbbbbbbbbb", "c"])

    def test_given_a_hint_over_budget_then_it_is_kept_whole_and_all_terms_are_dropped(self):
        result = build_prompt("a b c d e", ["t1"], count_tokens=words, budget=3)
        self.assertEqual(result.text, "a b c d e")
        self.assertEqual(result.dropped, ["t1"])
        self.assertTrue(result.hint_over_budget)

    def test_duplicate_and_blank_terms_are_ignored(self):
        result = build_prompt(None, ["Advisior", " ", "advisior", "Cotedo "], count_tokens=words)
        self.assertEqual(result.text, "Advisior, Cotedo")

    def test_correction_targets_are_appended_after_vocabulary_without_duplicates(self):
        result = build_prompt(
            None,
            ["Advisior"],
            count_tokens=words,
            extra_terms=["Prod", "Advisior", "Cotedo"],
        )
        self.assertEqual(result.text, "Advisior, Prod, Cotedo")

    def test_whisper_budget_is_223_tokens(self):
        self.assertEqual(WHISPER_PROMPT_TOKENS, 223)


class EffectivePromptTests(unittest.TestCase):
    def test_existing_config_with_only_initial_prompt_is_passed_unchanged(self):
        config = Config(initial_prompt="Advisior, Cotedo, KiCo")
        self.assertEqual(effective_prompt(config, count_tokens=words), "Advisior, Cotedo, KiCo")

    def test_corrections_are_not_used_unless_enabled(self):
        config = Config(initial_prompt="Deutsch.", corrections={"Brot": "Prod"})
        self.assertEqual(effective_prompt(config, count_tokens=words), "Deutsch.")

    def test_corrections_targets_are_used_when_enabled(self):
        config = Config(
            initial_prompt="Deutsch.",
            vocabulary=["Advisior"],
            corrections={"Brot": "Prod", "Advisor": "Advisior"},
            vocabulary_from_corrections=True,
        )
        self.assertEqual(effective_prompt(config, count_tokens=words), "Deutsch. Advisior, Prod")

    def test_dropped_terms_are_logged_as_a_warning(self):
        config = Config(initial_prompt="a b", vocabulary=["t1", "t2", "t3"])
        with self.assertLogs("claude_stt.prompt", level="WARNING") as logs:
            effective_prompt(config, count_tokens=words, budget=3)
        self.assertIn("t2, t3", "\n".join(logs.output))

    def test_engine_factory_passes_the_effective_prompt_to_whisper(self):
        config = Config(engine="whisper", initial_prompt="Deutsch.", vocabulary=["Advisior"])
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLAUDE_STT_INITIAL_PROMPT", None)
            engine = build_engine(config)
        self.assertEqual(engine.initial_prompt, "Deutsch. Advisior")

    def test_default_token_counter_counts_something_for_non_empty_text(self):
        from claude_stt.prompt import count_tokens

        self.assertGreater(count_tokens("Advisior"), 0)
        self.assertEqual(count_tokens(""), 0)


class VocabularyConfigTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.config_dir = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"LOCAL_STT_CONFIG_DIR": tmp.name})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("CLAUDE_PLUGIN_ROOT", None)

    def _write(self, text: str) -> None:
        (self.config_dir / "config.toml").write_text(text)

    def test_old_config_with_a_single_initial_prompt_loads_as_the_hint(self):
        self._write('[claude-stt]\ninitial_prompt = "Advisior, Cotedo"\n')
        config = Config.load()
        self.assertEqual(config.initial_prompt, "Advisior, Cotedo")
        self.assertEqual(config.vocabulary, [])
        self.assertFalse(config.vocabulary_from_corrections)

    def test_loading_an_old_config_does_not_rewrite_the_file(self):
        original = '[claude-stt]\ninitial_prompt = "Advisior"\n\n[corrections]\n"a" = "b"\n'
        self._write(original)
        Config.load()
        self.assertEqual((self.config_dir / "config.toml").read_text(), original)

    def test_vocabulary_list_is_loaded(self):
        self._write(
            '[claude-stt]\ninitial_prompt = "Deutsch."\n'
            'vocabulary = ["Advisior", "Cotedo"]\nvocabulary_from_corrections = true\n'
        )
        config = Config.load()
        self.assertEqual(config.vocabulary, ["Advisior", "Cotedo"])
        self.assertTrue(config.vocabulary_from_corrections)

    def test_vocabulary_given_as_a_comma_separated_string_is_split(self):
        config = Config(vocabulary="Advisior, Cotedo ,,KiCo").validate()
        self.assertEqual(config.vocabulary, ["Advisior", "Cotedo", "KiCo"])

    def test_invalid_vocabulary_is_reset_with_a_warning(self):
        with self.assertLogs("claude_stt.config", level="WARNING"):
            config = Config(vocabulary=42).validate()
        self.assertEqual(config.vocabulary, [])

    def test_non_string_terms_are_dropped(self):
        config = Config(vocabulary=["Advisior", 3, None, " Cotedo "]).validate()
        self.assertEqual(config.vocabulary, ["Advisior", "Cotedo"])

    def test_vocabulary_round_trips_through_save(self):
        Config(
            initial_prompt="Deutsch.", vocabulary=["Advisior"], vocabulary_from_corrections=True
        ).save()
        config = Config.load()
        self.assertEqual(config.initial_prompt, "Deutsch.")
        self.assertEqual(config.vocabulary, ["Advisior"])
        self.assertTrue(config.vocabulary_from_corrections)

    def test_save_omits_new_keys_when_unused(self):
        Config().save()
        text = (self.config_dir / "config.toml").read_text()
        self.assertNotIn("vocabulary", text)


if __name__ == "__main__":
    unittest.main()
