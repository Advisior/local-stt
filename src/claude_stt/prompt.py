"""Build the Whisper initial prompt from a hint and a vocabulary (#51).

Whisper keeps only the last 223 prompt tokens and silently cuts the start,
which is where the style and language hint sits. The prompt is therefore
built here: hint first, then vocabulary terms in order, as many as fit.
Terms that do not fit are dropped and logged instead of cutting the hint.
"""

from __future__ import annotations

import functools
import logging
import math
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
    if tokenizer is not None:
        # Whisper encodes the prompt with a leading space.
        return len(tokenizer.encode(" " + text.strip()))
    # Multilingual BPE averages more than 3 UTF-8 bytes per token for German
    # and English; 3 overestimates, so terms are dropped rather than the hint.
    return math.ceil(len(text.encode("utf-8")) / 3)


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


def effective_prompt(
    config: Config,
    count_tokens: TokenCounter = count_tokens,
    budget: int = WHISPER_PROMPT_TOKENS,
) -> str | None:
    """Prompt to pass to Whisper for this config; logs what did not fit."""
    extra = list(config.corrections.values()) if config.vocabulary_from_corrections else []
    result = build_prompt(
        config.initial_prompt,
        config.vocabulary,
        count_tokens=count_tokens,
        budget=budget,
        extra_terms=extra,
    )
    if result.hint_over_budget:
        logger.warning(
            "initial_prompt is longer than Whisper's %d-token prompt; Whisper will cut "
            "its beginning. Move proper nouns to 'vocabulary'.",
            budget,
        )
    if result.dropped:
        logger.warning(
            "Vocabulary does not fit Whisper's %d-token prompt; dropped %d term(s): %s",
            budget,
            len(result.dropped),
            ", ".join(result.dropped),
        )
    return result.text
