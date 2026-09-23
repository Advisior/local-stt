"""Offline lookups in the local Hugging Face model cache."""

from __future__ import annotations

from typing import Iterable, Optional


def is_cached(
    repo_id: str, filenames: Iterable[str], cache_dir: Optional[str] = None
) -> bool:
    """Return True if every file of a Hub repo is already in the local cache.

    Never touches the network, so it is safe to call before deciding whether
    the daemon may run with HF_HUB_OFFLINE=1.
    """
    try:
        from huggingface_hub import try_to_load_from_cache
    except ImportError:
        return False
    try:
        return all(
            isinstance(try_to_load_from_cache(repo_id, name, cache_dir=cache_dir), str)
            for name in filenames
        )
    except ValueError:
        # Not a valid repo id, e.g. a local path that does not exist.
        return False
