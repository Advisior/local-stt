"""ASR benchmark script (#50, AC-8 to AC-12)."""

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import wave
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "asr_benchmark.py"

_spec = importlib.util.spec_from_file_location("asr_benchmark", SCRIPT)
bench = importlib.util.module_from_spec(_spec)
sys.modules["asr_benchmark"] = bench  # dataclasses look the module up
_spec.loader.exec_module(bench)


def write_wav(path: Path, seconds: float) -> None:
    samples = (np.sin(np.arange(int(16000 * seconds)) / 5) * 8000).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(samples.tobytes())


class _FakeEngine:
    """Answers by audio length, so each generated WAV has a known transcript."""

    BY_SAMPLES = {8000: "Hallo, Welt!", 4000: "das ist kein Test", 2000: "ohne Referenz"}

    def __init__(self, config):
        self.config = config

    def is_available(self):
        return True

    def load_model(self):
        return True

    def transcribe(self, audio, sample_rate=16000):
        text = self.BY_SAMPLES[len(audio)]
        if self.config.initial_prompt:
            text += " " + self.config.initial_prompt
        return text


def fake_build_engine(config):
    if config.engine != "fake":
        raise bench.EngineError(f"Unknown engine '{config.engine}'")
    return _FakeEngine(config)


class _BenchCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.config_dir = self.tmp / "config"
        self.config_dir.mkdir()
        (self.config_dir / "config.toml").write_text(
            '[claude-stt]\nengine = "mlx"\nwhisper_model = "large-v3-turbo"\n'
            'language = "de"\ninitial_prompt = "aus der Config"\n'
        )
        self._env = mock.patch.dict(os.environ, {"LOCAL_STT_CONFIG_DIR": str(self.config_dir)})
        self._env.start()
        self.folder = self.tmp / "asr"
        self.folder.mkdir()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(bench, "build_engine", fake_build_engine):
            with redirect_stdout(out), redirect_stderr(err):
                code = bench.main([str(self.folder), *argv])
        return code, out.getvalue(), err.getvalue()

    def add_fixtures(self):
        write_wav(self.folder / "a.wav", 0.5)
        (self.folder / "a.ref.txt").write_text("hallo welt\n", encoding="utf-8")
        write_wav(self.folder / "b.wav", 0.25)
        (self.folder / "b.ref.txt").write_text("Das ist ein Test.", encoding="utf-8")


class BenchmarkRunTests(_BenchCase):
    def test_ac8_given_two_wavs_and_two_variants_then_each_is_reported_with_summary(self):
        self.add_fixtures()
        code, out, _ = self.run_main("--variant", "engine=fake", "--variant", "engine=fake,prompt=extra")
        self.assertEqual(code, 0)
        for name in ("a.wav", "b.wav"):
            self.assertEqual(out.count(f"== {name} | "), 2)
        self.assertIn("Hallo, Welt!", out)
        self.assertIn("das ist kein Test", out)
        self.assertRegex(out, r"latency \d+\.\d\d s")
        self.assertIn("WER 0.0 %", out)
        self.assertIn("WER 25.0 %", out)
        summary = out.split("Summary", 1)[1]
        self.assertIn("engine=fake,prompt=extra", summary)
        self.assertRegex(summary, r"engine=fake\s+12\.5 %\s+\d+\.\d\d s\s+0")

    def test_ac9_given_prompt_from_file_then_file_text_is_the_prompt(self):
        self.add_fixtures()
        prompt_file = self.tmp / "prompt.txt"
        prompt_file.write_text("aus Datei\n", encoding="utf-8")
        code, out, _ = self.run_main("--variant", f"engine=fake,prompt=@{prompt_file}")
        self.assertEqual(code, 0)
        self.assertIn("Hallo, Welt! aus Datei", out)

    def test_ac9_given_prompt_config_then_config_prompt_is_used(self):
        self.add_fixtures()
        code, out, _ = self.run_main("--variant", "engine=fake,prompt=config")
        self.assertEqual(code, 0)
        self.assertIn("Hallo, Welt! aus der Config", out)

    def test_ac9_given_prompt_with_comma_then_it_stays_one_value(self):
        variant = bench.parse_variant("engine=fake,prompt=Hallo, Welt", bench.Config())
        self.assertEqual(variant.prompt, "Hallo, Welt")

    def test_ac9_given_spec_then_keys_map_onto_a_copied_config(self):
        base = bench.Config(engine="mlx", whisper_model="large-v3-turbo", language="de",
                            initial_prompt="cfg")
        variant = bench.parse_variant("model=large-v3,language=auto", base)
        config = bench.variant_config(variant, base)
        self.assertEqual((config.engine, config.whisper_model, config.language, config.initial_prompt),
                         ("mlx", "large-v3", None, None))
        self.assertEqual(base.whisper_model, "large-v3-turbo")
        moon = bench.variant_config(bench.parse_variant("engine=moonshine,model=moonshine/tiny", base), base)
        self.assertEqual(moon.moonshine_model, "moonshine/tiny")

    def test_ac10_given_wav_without_reference_then_wer_is_na_and_run_succeeds(self):
        self.add_fixtures()
        write_wav(self.folder / "c.wav", 0.125)
        code, out, _ = self.run_main("--variant", "engine=fake")
        self.assertEqual(code, 0)
        block = out.split("== c.wav", 1)[1].split("==", 1)[0]
        self.assertIn("ohne Referenz", block)
        self.assertIn("WER n/a", block)
        self.assertRegex(out.split("Summary", 1)[1], r"engine=fake\s+12\.5 %\s+\d+\.\d\d s\s+1")

    def test_ac11_given_json_path_then_all_results_are_written(self):
        self.add_fixtures()
        target = self.tmp / "out" / "results.json"
        code, _, _ = self.run_main("--variant", "engine=fake", "--json", str(target))
        self.assertEqual(code, 0)
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual([r["file"] for r in data["results"]], ["a.wav", "b.wav"])
        b = data["results"][1]
        self.assertEqual(b["variant"], "engine=fake")
        self.assertEqual(b["transcript"], "das ist kein Test")
        self.assertEqual(b["reference"], "Das ist ein Test.")
        self.assertAlmostEqual(b["wer"], 0.25)
        self.assertIsInstance(b["latency_s"], float)
        self.assertEqual(data["summary"][0]["files_without_reference"], 0)
        self.assertAlmostEqual(data["summary"][0]["mean_wer"], 0.125)

    def test_ac12_given_wer_above_zero_then_word_diff_is_printed(self):
        self.add_fixtures()
        _, out, _ = self.run_main("--variant", "engine=fake")
        b_block = out.split("== b.wav", 1)[1]
        self.assertIn("diff: -kein +ein", b_block)
        a_block = out.split("== a.wav", 1)[1].split("== b.wav", 1)[0]
        self.assertNotIn("diff:", a_block)


class WordErrorRateTests(unittest.TestCase):
    def test_ac12_given_case_and_punctuation_differences_then_wer_is_zero(self):
        self.assertEqual(bench.word_error_rate("Hallo, Welt!", "hallo welt"), 0.0)

    def test_ac12_given_substitution_insertion_and_deletion_then_wer_counts_each(self):
        self.assertAlmostEqual(bench.word_error_rate("a b c d", "a x c d"), 0.25)
        self.assertAlmostEqual(bench.word_error_rate("a b", "a b c"), 0.5)
        self.assertAlmostEqual(bench.word_error_rate("a b c d", "a b"), 0.5)

    def test_ac12_given_umlauts_then_they_are_kept_as_letters(self):
        self.assertEqual(bench.normalize_words("Größe: Übermaß."), ["größe", "übermaß"])

    def test_ac12_given_empty_reference_then_each_hypothesis_word_counts_as_error(self):
        self.assertEqual(bench.word_error_rate("", ""), 0.0)
        self.assertEqual(bench.word_error_rate("", "äh hallo"), 2.0)

    def test_ac12_word_diff_marks_wrong_words_minus_and_right_words_plus(self):
        self.assertEqual(bench.word_diff("das ist ein Test", "das ist kein test bitte"),
                         "-kein +ein -bitte")


class BenchmarkCliTests(unittest.TestCase):
    """Runs the script as a process, as Uwe does."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.env = {**os.environ, "LOCAL_STT_CONFIG_DIR": str(self.tmp / "config")}

    def tearDown(self):
        self._tmp.cleanup()

    def run_script(self, *argv):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *argv],
            capture_output=True, text=True, env=self.env, timeout=120,
        )

    def test_ac10_given_folder_without_wav_then_exit_1_and_say_so(self):
        result = self.run_script(str(self.tmp), "--variant", "engine=mlx")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no .wav files", result.stderr)

    def test_ac9_given_unknown_key_then_exit_2_naming_the_spec(self):
        write_wav(self.tmp / "a.wav", 0.1)
        result = self.run_script(str(self.tmp), "--variant", "engine=mlx,temperature=0")
        self.assertEqual(result.returncode, 2)
        self.assertIn("engine=mlx,temperature=0", result.stderr)
        self.assertIn("temperature", result.stderr)

    def test_ac9_given_missing_prompt_file_then_exit_2_naming_the_spec(self):
        write_wav(self.tmp / "a.wav", 0.1)
        spec = f"prompt=@{self.tmp / 'missing.txt'}"
        result = self.run_script(str(self.tmp), "--variant", spec)
        self.assertEqual(result.returncode, 2)
        self.assertIn(spec, result.stderr)

    def test_ac9_given_unknown_engine_then_exit_2_naming_the_spec(self):
        write_wav(self.tmp / "a.wav", 0.1)
        result = self.run_script(str(self.tmp), "--variant", "engine=nope")
        self.assertEqual(result.returncode, 2)
        self.assertIn("engine=nope", result.stderr)


if __name__ == "__main__":
    unittest.main()
