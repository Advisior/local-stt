"""Transcript history file and private mode state.

``history.jsonl`` has two writers: the daemon appends dictations and the menu
bar app deletes single entries. Both take an exclusive lock on
``history.lock`` and replace the file atomically (temp file in the same
directory plus rename), so neither can lose the other's change.

``private_mode.json`` is written by the menu bar app and only read here.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from .config import Config

HISTORY_FILE = "history.jsonl"
LOCK_FILE = "history.lock"
PRIVATE_MODE_FILE = "private_mode.json"
MAX_ENTRIES = 100

_logger = logging.getLogger(__name__)


def _resolve_dir(config_dir: Optional[Path]) -> Path:
    return Path(config_dir) if config_dir is not None else Config.get_config_dir()


if os.name == "nt":
    import msvcrt

    def _lock_fd(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)

    def _unlock_fd(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock_fd(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _unlock_fd(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def history_lock(config_dir: Optional[Path] = None) -> Iterator[Path]:
    """Hold the exclusive cross-process lock on ``history.lock``."""
    directory = _resolve_dir(config_dir)
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory / LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        _lock_fd(fd)
        try:
            yield directory
        finally:
            _unlock_fd(fd)
    finally:
        os.close(fd)


def _read_lines(path: Path) -> list[bytes]:
    """Raw non-empty lines as bytes.

    Kept undecoded so foreign or invalid UTF-8 lines survive a rewrite
    instead of failing the whole read.
    """
    try:
        return [line for line in path.read_bytes().splitlines() if line.strip()]
    except FileNotFoundError:
        return []


def _write_lines_atomic(path: Path, lines: list[bytes]) -> None:
    content = b"".join(line + b"\n" for line in lines)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".history.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def append_entry(entry: dict, config_dir: Optional[Path] = None) -> None:
    """Append one entry, keeping the last ``MAX_ENTRIES`` lines."""
    with history_lock(config_dir) as directory:
        path = directory / HISTORY_FILE
        lines = _read_lines(path)
        lines.append(json.dumps(entry).encode("utf-8"))
        _write_lines_atomic(path, lines[-MAX_ENTRIES:])


def _matches(line: bytes, timestamp: str, text: str) -> bool:
    try:
        data = json.loads(line)
    except ValueError:  # includes UnicodeDecodeError
        return False
    return isinstance(data, dict) and data.get("timestamp") == timestamp and data.get("text") == text


def delete_entry(timestamp: str, text: str, config_dir: Optional[Path] = None) -> bool:
    """Remove the first entry with this timestamp and text.

    Returns False and leaves the file untouched when no entry matches.
    """
    with history_lock(config_dir) as directory:
        path = directory / HISTORY_FILE
        lines = _read_lines(path)
        for index, line in enumerate(lines):
            if _matches(line, timestamp, text):
                del lines[index]
                _write_lines_atomic(path, lines)
                return True
        return False


def private_mode_active(now: Optional[datetime] = None, config_dir: Optional[Path] = None) -> bool:
    """Whether private mode is on. Fails closed: unreadable state means on.

    State file: ``{"until": "<ISO-8601 UTC>"}`` or ``{"until": null}``
    (until turned off). No file means off.
    """
    path = _resolve_dir(config_dir) / PRIVATE_MODE_FILE
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    except (OSError, UnicodeError) as exc:
        _logger.warning("Cannot read %s (%s); treating private mode as on", PRIVATE_MODE_FILE, type(exc).__name__)
        return True

    try:
        data = json.loads(raw)
        until = data["until"]
        if until is None:
            return True
        if not isinstance(until, str):
            raise ValueError("until is not a string")
        end = datetime.fromisoformat(until)
        if end.tzinfo is None:
            raise ValueError("until has no timezone")
    except (ValueError, TypeError, KeyError):
        _logger.warning("Malformed %s; treating private mode as on", PRIVATE_MODE_FILE)
        return True

    current = now or datetime.now(timezone.utc)
    return current < end
