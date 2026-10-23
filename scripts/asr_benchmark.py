#!/usr/bin/env python3
"""Run recorded dictations through several ASR variants and compare word error rates (#50).

Usage:
    uv run python scripts/asr_benchmark.py <folder> --variant <spec> [--variant <spec> ...]
        [--json <path>]

Every ``*.wav`` in <folder> (16-bit PCM, as the debug recording store writes
them) is transcribed with every variant. ``<name>.ref.txt`` next to a WAV is
its reference transcript; without one, or with an empty one, the WER is ``n/a``.
All variants load their models before the first transcription.

A variant spec is ``key=value`` pairs separated by commas:
    engine    moonshine | whisper | mlx | parakeet (default: config.toml)
    model     model name for that engine (default: config.toml)
    language  language code, ``auto`` for detection (default: config.toml)
    prompt    literal text, ``@path`` to read a file, ``config`` for the
              initial_prompt from config.toml (default: no prompt)
A comma only starts a new pair when ``<key>=`` follows it, so a literal prompt
may contain commas. Use ``@path`` for prompts that contain ``word=``.

Engines are built with ``engine_factory.build_engine`` from a copy of the
loaded config, so model names map exactly as in the daemon.

Exit codes: 0 done, 1 no WAV or unreadable input, 2 invalid variant, or its
engine or model cannot be loaded.
"""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import json
import re
import sys
import time
import unicodedata
import wave
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from claude_stt.config import Config
from claude_stt.engine_factory import build_engine
from claude_stt.errors import EngineError

VARIANT_KEYS = ("engine", "model", "language", "prompt")
ENGINES = ("moonshine", "whisper", "mlx", "parakeet")
EXIT_INPUT = 1
EXIT_SPEC = 2
_PAIR_SPLIT = re.compile(r",(?=\s*[A-Za-z_]\w*\s*=)")
_MODEL_FIELD = {"moonshine": "moonshine_model", "parakeet": "parakeet_model"}


class SpecError(Exception):
    """A variant spec that cannot be used. The message names the spec."""


@dataclasses.dataclass
class Variant:
    spec: str
    engine: str
    model: str
    language: Optional[str]
    prompt: Optional[str]


def _model_field(engine: str) -> str:
    return _MODEL_FIELD.get(engine, "whisper_model")


def parse_variant(spec: str, base: Config) -> Variant:
    """Parse ``key=value,...``; missing keys fall back to ``base`` (prompt to none)."""
    values: dict[str, str] = {}
    for pair in _PAIR_SPLIT.split(spec):
        key, sep, value = pair.partition("=")
        key = key.strip()
        if not sep or not key:
            raise SpecError(f"variant '{spec}': expected key=value, got '{pair}'")
        if key not in VARIANT_KEYS:
            raise SpecError(
                f"variant '{spec}': unknown key '{key}' (allowed: {', '.join(VARIANT_KEYS)})"
            )
        if key in values:
            raise SpecError(f"variant '{spec}': key '{key}' given twice")
        values[key] = value.strip()

    engine = values.get("engine") or base.engine
    if engine not in ENGINES:
        raise SpecError(f"variant '{spec}': unknown engine '{engine}' (allowed: {', '.join(ENGINES)})")
    model = values.get("model") or getattr(base, _model_field(engine))
    language = values.get("language", base.language or "auto")
    return Variant(
        spec=spec,
        engine=engine,
        model=model,
        language=None if language in ("", "auto") else language,
        prompt=_resolve_prompt(spec, values.get("prompt", ""), base),
    )


def _resolve_prompt(spec: str, raw: str, base: Config) -> Optional[str]:
    if raw == "config":
        return base.initial_prompt or None
    if raw.startswith("@"):
        path = Path(raw[1:]).expanduser()
        try:
            return path.read_text(encoding="utf-8").strip() or None
        except OSError as exc:
            raise SpecError(f"variant '{spec}': cannot read prompt file {path} ({exc.strerror})") from exc
    return raw or None


def variant_config(variant: Variant, base: Config) -> Config:
    """Copy of ``base`` with the variant applied; ``base`` stays untouched."""
    return dataclasses.replace(
        base,
        engine=variant.engine,
        language=variant.language,
        initial_prompt=variant.prompt,
        corrections=dict(base.corrections),
        **{_model_field(variant.engine): variant.model},
    )


def normalize_words(text: str) -> list[str]:
    """Lowercase words with punctuation (Unicode category P) removed."""
    stripped = "".join(" " if unicodedata.category(ch).startswith("P") else ch for ch in text.lower())
    return stripped.split()


def _edit_distance(ref: list[str], hyp: list[str]) -> int:
    previous = list(range(len(hyp) + 1))
    for i, ref_word in enumerate(ref, 1):
        current = [i]
        for j, hyp_word in enumerate(hyp, 1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (ref_word != hyp_word),
            ))
        previous = current
    return previous[-1]


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Levenshtein distance over normalized words / reference word count.

    An empty reference divides by 1, so every hallucinated word counts as one error.
    """
    ref, hyp = normalize_words(reference), normalize_words(hypothesis)
    return _edit_distance(ref, hyp) / max(len(ref), 1)


def word_diff(reference: str, hypothesis: str) -> str:
    """``-wrong +right`` per change: ``-`` = transcript word, ``+`` = reference word."""
    ref, hyp = normalize_words(reference), normalize_words(hypothesis)
    parts = []
    for tag, h1, h2, r1, r2 in difflib.SequenceMatcher(None, hyp, ref, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        parts += [f"-{w}" for w in hyp[h1:h2]] + [f"+{w}" for w in ref[r1:r2]]
    return " ".join(parts)


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """Float32 mono samples in [-1, 1] and the sample rate."""
    with wave.open(str(path), "rb") as wav:
        if wav.getsampwidth() != 2:
            raise ValueError("only 16-bit PCM is supported")
        channels, rate = wav.getnchannels(), wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, rate


def _build(variant: Variant, base: Config):
    try:
        engine = build_engine(variant_config(variant, base))
    except EngineError as exc:
        raise SpecError(f"variant '{variant.spec}': {exc}") from exc
    if not engine.is_available():
        raise SpecError(f"variant '{variant.spec}': engine '{variant.engine}' is not installed")
    if not engine.load_model():
        raise SpecError(f"variant '{variant.spec}': model '{variant.model}' failed to load")
    return engine


def _fmt_wer(wer: Optional[float]) -> str:
    return "n/a" if wer is None else f"{wer * 100:.1f} %"


def load_inputs(wavs: list[Path]) -> list[tuple[Path, np.ndarray, int, Optional[str]]]:
    """Samples, rate and reference text per WAV; ``None`` when ``.ref.txt`` is missing or blank."""
    inputs = []
    for path in wavs:
        samples, rate = read_wav(path)
        ref_path = path.with_name(f"{path.stem}.ref.txt")
        reference = ref_path.read_text(encoding="utf-8").strip() if ref_path.exists() else ""
        reference = reference or None  # empty or blank file = no reference
        inputs.append((path, samples, rate, reference))
    return inputs


def run(inputs: list, variants: list[Variant], base: Config) -> list[dict]:
    """Transcribe every input with every variant, printing as it goes.

    All engines are built and loaded first, so a variant that cannot load
    stops the run before any transcription instead of discarding results.
    """
    engines = [_build(variant, base) for variant in variants]
    results = []
    for variant, engine in zip(variants, engines):
        for path, samples, rate, reference in inputs:
            started = time.perf_counter()
            transcript = engine.transcribe(samples, rate).strip()
            latency = time.perf_counter() - started
            wer = None if reference is None else word_error_rate(reference, transcript)
            print(f"== {path.name} | {variant.spec}")
            print(f"   {transcript}")
            print(f"   latency {latency:.2f} s   WER {_fmt_wer(wer)}")
            if wer:
                print(f"   diff: {word_diff(reference, transcript)}")
            results.append({
                "file": path.name, "variant": variant.spec, "engine": variant.engine,
                "model": variant.model, "language": variant.language, "prompt": variant.prompt,
                "transcript": transcript, "reference": reference,
                "latency_s": round(latency, 3), "wer": wer,
            })
    return results


def summarize(results: list[dict], variants: list[Variant]) -> list[dict]:
    summary = []
    for variant in variants:
        rows = [r for r in results if r["variant"] == variant.spec]
        wers = [r["wer"] for r in rows if r["wer"] is not None]
        summary.append({
            "variant": variant.spec,
            "mean_wer": sum(wers) / len(wers) if wers else None,
            "mean_latency_s": sum(r["latency_s"] for r in rows) / len(rows) if rows else None,
            "files_without_reference": len(rows) - len(wers),
        })
    return summary


def print_summary(summary: list[dict]) -> None:
    width = max([len(s["variant"]) for s in summary] + [7])
    print()
    print("Summary")
    print(f"{'variant':<{width}}  {'mean WER':>9}  {'mean latency':>12}  without ref")
    for s in summary:
        latency = "n/a" if s["mean_latency_s"] is None else f"{s['mean_latency_s']:.2f} s"
        print(f"{s['variant']:<{width}}  {_fmt_wer(s['mean_wer']):>9}  {latency:>12}  "
              f"{s['files_without_reference']}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare ASR variants on recorded WAVs by word error rate.",
        epilog="Spec keys: engine, model, language (auto = detect), prompt (text, @file, config).",
    )
    parser.add_argument("folder", type=Path, help="folder with *.wav and optional <name>.ref.txt")
    parser.add_argument("--variant", action="append", required=True, metavar="SPEC",
                        help="e.g. engine=mlx,model=large-v3,language=de,prompt=@prompt.txt")
    parser.add_argument("--json", type=Path, metavar="PATH", help="also write all results as JSON")
    args = parser.parse_args(argv)

    base = Config.load()
    try:
        variants = [parse_variant(spec, base) for spec in args.variant]
        wavs = sorted(args.folder.glob("*.wav")) if args.folder.is_dir() else []
    except SpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_SPEC
    if not wavs:
        print(f"error: no .wav files in {args.folder}", file=sys.stderr)
        return EXIT_INPUT
    try:
        inputs = load_inputs(wavs)
    except (OSError, EOFError, ValueError, wave.Error) as exc:
        print(f"error: cannot read input ({type(exc).__name__}: {exc})", file=sys.stderr)
        return EXIT_INPUT
    try:
        results = run(inputs, variants, base)
    except SpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_SPEC

    summary = summarize(results, variants)
    print_summary(summary)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = {"variants": [dataclasses.asdict(v) for v in variants],
                   "results": results, "summary": summary}
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
