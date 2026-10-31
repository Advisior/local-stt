"""Pause flag the Settings hotkey recorder sets while it captures a shortcut.

The daemon's hotkeys would otherwise fire and, on macOS, swallow the key
system-wide (``ctrl+f1`` while the record hotkey is ``f1``), so the
recorder never sees it (#49). The app touches the file every few seconds
while recording and removes it afterwards; a file older than ``MAX_AGE_S``
counts as gone, so a crashed app cannot leave the hotkeys off.
"""

import time

from .config import Config

PAUSE_FILE = "hotkeys_paused"
MAX_AGE_S = 10.0


def paused() -> bool:
    """Whether the hotkey recorder is active. Never raises."""
    try:
        mtime = (Config.get_config_dir() / PAUSE_FILE).stat().st_mtime
    except OSError:
        return False
    return time.time() - mtime <= MAX_AGE_S
