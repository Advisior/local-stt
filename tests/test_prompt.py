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
        from claude_stt.prompt import PromptRefresher

        config = Config(initial_prompt="a b", vocabulary=["t1", "t2", "t3"])
        refresher = PromptRefresher(config, count_tokens=words, budget=3)
        with mock.patch("claude_stt.prompt.write_status"), self.assertLogs(
            "claude_stt.prompt", level="WARNING"
        ) as logs:
            refresher.refresh(FakeEngine(), reload=False)
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
    """vocabulary and vocabulary_from_corrections live in [claude-stt] of config.toml."""

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

    def test_loading_an_old_config_does_not_rewrite_or_create_files(self):
        original = '[claude-stt]\ninitial_prompt = "Advisior"\n\n[corrections]\n"a" = "b"\n'
        self._write(original)
        Config.load()
        self.assertEqual((self.config_dir / "config.toml").read_text(), original)
        self.assertEqual(sorted(p.name for p in self.config_dir.iterdir()), ["config.toml"])

    def test_vocabulary_keys_are_loaded(self):
        self._write(
            '[claude-stt]\ninitial_prompt = "Deutsch."\n'
            'vocabulary = [\n    "Advisior",\n    "Cotedo",\n]\n'
            "vocabulary_from_corrections = true\n"
        )
        config = Config.load()
        self.assertEqual(config.vocabulary, ["Advisior", "Cotedo"])
        self.assertTrue(config.vocabulary_from_corrections)

    def test_vocabulary_keys_round_trip_through_save(self):
        Config(
            initial_prompt="Deutsch.", vocabulary=["Advisior"], vocabulary_from_corrections=True
        ).save()
        config = Config.load()
        self.assertEqual(config.initial_prompt, "Deutsch.")
        self.assertEqual(config.vocabulary, ["Advisior"])
        self.assertTrue(config.vocabulary_from_corrections)

    def test_save_omits_the_vocabulary_keys_when_unused(self):
        Config().save()
        self.assertNotIn("vocabulary", (self.config_dir / "config.toml").read_text())

    def test_reload_vocabulary_picks_up_edits(self):
        self._write('[claude-stt]\nhotkey = "f1"\n')
        config = Config.load()
        self._write('[claude-stt]\nvocabulary = ["Cotedo"]\nvocabulary_from_corrections = true\n')
        config.reload_vocabulary()
        self.assertEqual(config.vocabulary, ["Cotedo"])
        self.assertTrue(config.vocabulary_from_corrections)

    def test_reload_vocabulary_keeps_values_when_the_file_is_unreadable(self):
        self._write('[claude-stt]\nvocabulary = ["Advisior"]\n')
        config = Config.load()
        self._write("[claude-stt\nbroken")
        config.reload_vocabulary()
        self.assertEqual(config.vocabulary, ["Advisior"])

    def test_non_bool_vocabulary_from_corrections_is_off_with_a_warning(self):
        with self.assertLogs("claude_stt.config", level="WARNING"):
            config = Config(vocabulary_from_corrections="yes").validate()
        self.assertFalse(config.vocabulary_from_corrections)

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


class FallbackTokenCountTests(unittest.TestCase):
    """Without the Whisper tokenizer the count must never be below the real one."""

    def setUp(self):
        patcher = mock.patch("claude_stt.prompt._whisper_tokenizer", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_fallback_counts_utf8_bytes_of_the_encoded_prompt(self):
        from claude_stt.prompt import count_tokens

        # Byte-level BPE emits at least one byte per token, so bytes bound tokens.
        # 32 x "မြန်မာ" is 576 bytes and 576 multilingual Whisper tokens.
        text = "မြန်မာ" * 32
        self.assertGreaterEqual(count_tokens(text), 576)
        self.assertEqual(count_tokens("ab"), len(" ab".encode("utf-8")))

    def test_multilingual_term_at_the_boundary_is_dropped_not_the_hint(self):
        hint = "Deutsch."
        term = "မြန်မာ" * 12  # 216 bytes; hint + term exceeds 223
        result = build_prompt(hint, [term])
        self.assertEqual(result.text, hint)
        self.assertEqual(result.dropped, [term])

    def test_ascii_terms_up_to_the_bound_are_kept(self):
        term = "a" * 221  # " " + 221 + nothing else = 222 bytes
        result = build_prompt(None, [term])
        self.assertEqual(result.text, term)


class FakeEngine:
    def __init__(self, prompt=None):
        self.initial_prompt = prompt


class PromptRefresherTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.config_dir = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"LOCAL_STT_CONFIG_DIR": tmp.name})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("CLAUDE_PLUGIN_ROOT", None)

    def _refresher(self, config, budget=WHISPER_PROMPT_TOKENS):
        from claude_stt.prompt import PromptRefresher

        return PromptRefresher(config, count_tokens=words, budget=budget)

    def test_new_correction_target_reaches_the_engine_without_a_restart(self):
        (self.config_dir / "config.toml").write_text(
            '[claude-stt]\ninitial_prompt = "Deutsch."\nvocabulary_from_corrections = true\n'
        )
        config = Config.load()
        engine = FakeEngine()
        refresher = self._refresher(config)
        refresher.refresh(engine)
        self.assertEqual(engine.initial_prompt, "Deutsch.")

        # The History view adds a correction while the daemon runs.
        (self.config_dir / "config.toml").write_text(
            '[claude-stt]\ninitial_prompt = "Deutsch."\nvocabulary_from_corrections = true\n'
            '\n[corrections]\n"Brot" = "Prod"\n'
        )
        refresher.refresh(engine)
        self.assertEqual(engine.initial_prompt, "Deutsch. Prod")

    def test_vocabulary_edits_reach_the_engine_without_a_restart(self):
        (self.config_dir / "config.toml").write_text('[claude-stt]\nhotkey = "f1"\n')
        config = Config.load()
        engine = FakeEngine()
        refresher = self._refresher(config)
        refresher.refresh(engine)
        self.assertIsNone(engine.initial_prompt)
        (self.config_dir / "config.toml").write_text('[claude-stt]\nvocabulary = ["Advisior"]\n')
        refresher.refresh(engine)
        self.assertEqual(engine.initial_prompt, "Advisior")

    def test_unchanged_inputs_do_not_log_again(self):
        config = Config(initial_prompt="a b", vocabulary=["t1", "t2"])
        refresher = self._refresher(config, budget=3)
        engine = FakeEngine()
        with self.assertLogs("claude_stt.prompt", level="WARNING") as logs:
            refresher.refresh(engine, reload=False)
            refresher.refresh(engine, reload=False)
        self.assertEqual(len(logs.output), 1)

    def test_engines_without_a_prompt_are_left_alone(self):
        refresher = self._refresher(Config(vocabulary=["Advisior"]))
        engine = object()
        refresher.refresh(engine, reload=False)  # must not raise
        self.assertFalse((self.config_dir / "prompt_status.json").exists())

    def test_status_file_lists_dropped_terms_for_settings(self):
        import json

        config = Config(initial_prompt="a b", vocabulary=["t1", "t2", "t3"])
        with self.assertLogs("claude_stt.prompt", level="WARNING"):
            self._refresher(config, budget=3).refresh(FakeEngine(), reload=False)
        status = json.loads((self.config_dir / "prompt_status.json").read_text())
        self.assertEqual(status["budget"], 3)
        self.assertEqual(status["dropped"], ["t2", "t3"])
        self.assertFalse(status["hint_over_budget"])

    def test_status_file_is_cleared_when_everything_fits(self):
        import json

        config = Config(initial_prompt="a b", vocabulary=["t1"])
        self._refresher(config).refresh(FakeEngine(), reload=False)
        status = json.loads((self.config_dir / "prompt_status.json").read_text())
        self.assertEqual(status["dropped"], [])
        self.assertFalse(status["hint_over_budget"])

    def test_mock_engines_are_left_alone(self):
        engine = mock.Mock()
        self._refresher(Config(vocabulary=["Advisior"])).refresh(engine, reload=False)
        self.assertFalse((self.config_dir / "prompt_status.json").exists())


class EnvPromptTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = mock.patch.dict(
            os.environ,
            {"LOCAL_STT_CONFIG_DIR": tmp.name, "CLAUDE_STT_INITIAL_PROMPT": "Aus der Umgebung."},
        )
        env.start()
        self.addCleanup(env.stop)

    def _transcribe_kwargs(self, engine):
        engine.load_model = lambda: True
        engine._model = mock.Mock()
        engine._model.transcribe.return_value = ([], None)
        engine.transcribe(__import__("numpy").zeros(16000, dtype="float32"))
        return engine._model.transcribe.call_args.kwargs

    def test_env_prompt_survives_a_refresh_when_the_config_has_none(self):
        from claude_stt.engines.whisper import WhisperEngine
        from claude_stt.prompt import PromptRefresher

        config = Config(engine="whisper")
        engine = build_engine(config)
        PromptRefresher(config, count_tokens=words).refresh(engine, reload=False)
        self.assertIsInstance(engine, WhisperEngine)
        self.assertEqual(self._transcribe_kwargs(engine)["initial_prompt"], "Aus der Umgebung.")

    def test_config_prompt_still_wins_over_the_env_prompt(self):
        from claude_stt.prompt import PromptRefresher

        config = Config(engine="whisper", initial_prompt="Deutsch.")
        engine = build_engine(config)
        PromptRefresher(config, count_tokens=words).refresh(engine, reload=False)
        self.assertEqual(self._transcribe_kwargs(engine)["initial_prompt"], "Deutsch.")


class DaemonPromptTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.config_dir = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"LOCAL_STT_CONFIG_DIR": tmp.name})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("CLAUDE_PLUGIN_ROOT", None)

    def test_a_correction_added_while_running_steers_the_next_transcription(self):
        from claude_stt import daemon_service
        from claude_stt.daemon_service import STTDaemon

        (self.config_dir / "config.toml").write_text(
            '[claude-stt]\ninitial_prompt = "Deutsch."\nvocabulary_from_corrections = true\n'
        )
        d = STTDaemon(Config.load())
        d._overlay_send = mock.Mock()
        seen = []

        class Engine:
            initial_prompt = "Deutsch."

            def transcribe(self, audio, sample_rate):
                seen.append(self.initial_prompt)
                return "Hallo"

        d._engine = Engine()
        (self.config_dir / "config.toml").write_text(
            '[claude-stt]\ninitial_prompt = "Deutsch."\nvocabulary_from_corrections = true\n'
            '\n[corrections]\n"Brot" = "Prod"\n'
        )
        audio = daemon_service.np.ones(16000, dtype="float32") * 0.1
        with mock.patch.object(daemon_service, "output_text", return_value=None), \
                mock.patch.object(d, "_append_history"), \
                mock.patch.object(daemon_service, "play_sound"), \
                mock.patch.object(daemon_service, "get_active_window", return_value=None):
            d._process_transcription((audio, None))
        self.assertEqual(seen, ["Deutsch. Prod"])


if __name__ == "__main__":
    unittest.main()
