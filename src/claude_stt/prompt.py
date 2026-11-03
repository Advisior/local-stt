"""Build the Whisper initial prompt from a hint and a vocabulary (#51).

Whisper keeps only the last 223 prompt tokens and silently cuts the start,
which is where the style and language hint sits. The prompt is therefore
built here: hint first, then vocabulary terms in order, as many as fit.
Terms that do not fit are dropped and logged instead of cutting the hint.
The daemon refreshes the prompt before each transcription, so edits to
vocabulary.toml and new corrections apply without a restart, and writes
prompt_status.json for the Settings warning.
"""

from __future__ import annotations

import functools
import json
import logging
import os
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config

logger = logging.getLogger(__name__)

# Whisper decodes with n_text_ctx = 448 and keeps prompt[-(448 // 2 - 1):].
WHISPER_PROMPT_TOKENS = 223

TokenCounter = Callable[[str], int]


@dataclass
class PromptBuild:
    """Effective prompt text and the vocabulary terms left out of it."""

    text: str | None
    dropped: list[str] = field(default_factory=list)
    hint_over_budget: bool = False


@functools.lru_cache(maxsize=1)
def _whisper_tokenizer():
    try:
        from mlx_whisper.tokenizer import get_tokenizer
    except Exception:
        return None
    try:
        return get_tokenizer(multilingual=True)
    except Exception:
        logger.debug("Whisper tokenizer unavailable", exc_info=True)
        return None


def count_tokens(text: str) -> int:
    """Count Whisper tokens; without a tokenizer, estimate on the safe side."""
    if not text:
        return 0
    tokenizer = _whisper_tokenizer()
    # Whisper encodes the prompt with a leading space.
    text = " " + text.strip()
    if tokenizer is not None:
        return len(tokenizer.encode(text))
    # Byte-level BPE: every token covers at least one byte, so the UTF-8
    # length is an upper bound. It drops terms early, never cuts the hint.
    return len(text.encode("utf-8"))


def _unique_terms(terms: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        if not isinstance(term, str):
            continue
        term = term.strip()
        key = term.casefold()
        if term and key not in seen:
            seen.add(key)
            result.append(term)
    return result


def _join(hint: str, terms: list[str]) -> str:
    vocabulary = ", ".join(terms)
    if hint and vocabulary:
        return f"{hint} {vocabulary}"
    return hint or vocabulary


def build_prompt(
    hint: str | None,
    vocabulary: Iterable[str] | None,
    count_tokens: TokenCounter = count_tokens,
    budget: int = WHISPER_PROMPT_TOKENS,
    extra_terms: Iterable[str] | None = None,
) -> PromptBuild:
    """Combine hint and terms; keep term order and stop at the first that does not fit.

    The hint is never shortened. ``extra_terms`` (correction targets) come
    after the vocabulary, so they are dropped first.
    """
    hint = (hint or "").strip()
    terms = _unique_terms([*(vocabulary or []), *(extra_terms or [])])

    hint_over_budget = bool(hint) and count_tokens(hint) > budget
    if hint_over_budget:
        return PromptBuild(text=hint, dropped=terms, hint_over_budget=True)

    kept: list[str] = []
    for index, term in enumerate(terms):
        if count_tokens(_join(hint, [*kept, term])) > budget:
            return PromptBuild(text=_join(hint, kept) or None, dropped=terms[index:])
        kept.append(term)
    return PromptBuild(text=_join(hint, kept) or None)


def _build_for(config: Config, count_tokens: TokenCounter, budget: int) -> PromptBuild:
    extra = list(config.corrections.values()) if config.vocabulary_from_corrections else []
    return build_prompt(
        config.initial_prompt,
        config.vocabulary,
        count_tokens=count_tokens,
        budget=budget,
        extra_terms=extra,
    )


def effective_prompt(
    config: Config,
    count_tokens: TokenCounter = count_tokens,
    budget: int = WHISPER_PROMPT_TOKENS,
) -> str | None:
    """Prompt to pass to Whisper for this config (no logging)."""
    return _build_for(config, count_tokens, budget).text


class PromptRefresher:
    """Keeps an engine's prompt in step with config edits made while the daemon runs."""

    def __init__(
        self,
        config: Config,
        count_tokens: TokenCounter = count_tokens,
        budget: int = WHISPER_PROMPT_TOKENS,
    ):
        self.config = config
        self._count_tokens = count_tokens
        self._budget = budget
        self._last_inputs: tuple | None = None

    def refresh(self, engine: object, reload: bool = True) -> None:
        """Re-read corrections and vocabulary, rebuild the prompt when they changed.

        Corrections are reloaded for every engine, since they are applied to the
        transcript too; the prompt only matters for Whisper and MLX.
        """
        if reload:
            self.config.reload_corrections()
        if not isinstance(getattr(engine, "initial_prompt", 0), (str, type(None))):
            return  # Moonshine and Parakeet take no prompt.
        if reload:
            self.config.reload_vocabulary()
        inputs = (
            self.config.initial_prompt,
            tuple(self.config.vocabulary),
            self.config.vocabulary_from_corrections,
            tuple(self.config.corrections.values())
            if self.config.vocabulary_from_corrections
            else (),
        )
        if inputs == self._last_inputs:
            return
        self._last_inputs = inputs
        result = _build_for(self.config, self._count_tokens, self._budget)
        engine.initial_prompt = result.text
        self._report(result)

    def _report(self, result: PromptBuild) -> None:
        if result.hint_over_budget:
            logger.warning(
                "initial_prompt is longer than Whisper's %d-token prompt; Whisper will cut "
                "its beginning. Move proper nouns to vocabulary.toml.",
                self._budget,
            )
        if result.dropped:
            logger.warning(
                "Vocabulary does not fit Whisper's %d-token prompt; dropped %d term(s): %s",
                self._budget,
                len(result.dropped),
                ", ".join(result.dropped),
            )
        write_status(result, self._budget)


STATUS_FILE = "prompt_status.json"


def write_status(result: PromptBuild, budget: int) -> None:
    """Write what did not fit for the Settings warning; failures are only logged."""
    from .config import Config

    path = Config.get_config_dir() / STATUS_FILE
    status = {
        "budget": budget,
        "hint_over_budget": result.hint_over_budget,
        "dropped": result.dropped,
    }
    temp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", delete=False, dir=str(path.parent), suffix=".tmp"
        ) as handle:
            temp = handle.name
            json.dump(status, handle, ensure_ascii=False)
        os.replace(temp, path)
        temp = None
    except OSError:
        logger.debug("Could not write %s", path, exc_info=True)
    finally:
        if temp:
            try:
                os.unlink(temp)
            except OSError:
                pass
