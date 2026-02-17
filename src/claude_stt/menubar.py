"""macOS Menu Bar app for claude-stt."""

from __future__ import annotations

import logging
import subprocess
import threading
import time

try:
    import rumps
except ImportError:
    rumps = None

from .config import Config
from .daemon import (
    is_daemon_running,
    start_daemon,
    stop_daemon,
    toggle_recording,
)
from . import __version__

logger = logging.getLogger(__name__)

# Fallback emoji icons (used when SF Symbols unavailable)
EMOJI_STOPPED = "\u23f9"
EMOJI_RUNNING = "\U0001f3a4"

# SF Symbol names
SF_MIC = "mic.fill"
SF_MIC_SLASH = "mic.slash.fill"


def _set_sf_symbol(nsstatusitem, symbol_name):
    """Set an SF Symbol as menu bar icon. Returns True on success."""
    try:
        from AppKit import NSImage

        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            symbol_name, None
        )
        if image:
            image.setTemplate_(True)
            nsstatusitem.button().setImage_(image)
            nsstatusitem.button().setTitle_("")
            return True
    except Exception:
        pass
    return False


class STTMenuBarApp(rumps.App):
    """Menu bar application for controlling claude-stt daemon."""

    def __init__(self):
        self.config = Config.load().validate()
        self._sf_available = False
        self._nsstatusitem = None

        super().__init__(
            name="claude-stt",
            title=EMOJI_STOPPED,
            quit_button=None,
        )

        # --- Status ---
        self._status_item = rumps.MenuItem("Status: Checking...")
        self._status_item.set_callback(None)

        # --- Daemon control ---
        self._toggle_daemon = rumps.MenuItem(
            "Start Daemon", callback=self._on_toggle_daemon
        )
        self._toggle_record = rumps.MenuItem("Toggle Recording")
        self._toggle_record.set_callback(None)

        # --- Settings submenu ---
        self._hotkey_item = rumps.MenuItem(
            f"Hotkey: {self.config.hotkey}",
            callback=self._on_edit_hotkey,
        )

        self._mode_ptt = rumps.MenuItem(
            "Push-to-Talk", callback=self._on_set_mode_ptt
        )
        self._mode_toggle = rumps.MenuItem(
            "Toggle", callback=self._on_set_mode_toggle
        )
        self._update_mode_checks()

        self._lang_item = rumps.MenuItem(
            f"Language: {self.config.language or 'auto'}",
            callback=self._on_edit_language,
        )

        self._vocab_item = rumps.MenuItem(
            "Vocabulary...", callback=self._on_edit_vocab
        )

        self._sound_item = rumps.MenuItem(
            "Sound Effects", callback=self._on_toggle_sounds
        )
        self._sound_item.state = self.config.sound_effects

        # --- Info ---
        self._engine_item = rumps.MenuItem(f"Engine: {self._engine_label()}")
        self._engine_item.set_callback(None)

        self._restart_item = rumps.MenuItem(
            "Restart Daemon", callback=self._on_restart_daemon
        )

        self._open_log = rumps.MenuItem(
            "Open Log", callback=self._on_open_log
        )

        self._version_item = rumps.MenuItem(f"claude-stt v{__version__}")
        self._version_item.set_callback(None)

        self._quit_item = rumps.MenuItem("Quit", callback=self._on_quit)

        # --- Assemble menu ---
        self.menu = [
            self._status_item,
            None,
            self._toggle_daemon,
            self._toggle_record,
            None,
            (
                "Settings",
                [
                    self._hotkey_item,
                    ("Mode", [self._mode_ptt, self._mode_toggle]),
                    self._lang_item,
                    self._vocab_item,
                    None,
                    self._sound_item,
                ],
            ),
            self._restart_item,
            None,
            self._engine_item,
            self._open_log,
            None,
            self._version_item,
            self._quit_item,
        ]

    # ── Helpers ──────────────────────────────────────────────

    def _engine_label(self):
        e = self.config.engine
        if e == "mlx":
            return f"mlx ({self.config.whisper_model})"
        if e == "whisper":
            return f"whisper ({self.config.whisper_model})"
        return f"moonshine ({self.config.moonshine_model})"

    def _update_mode_checks(self):
        self._mode_ptt.state = self.config.mode == "push-to-talk"
        self._mode_toggle.state = self.config.mode == "toggle"

    def _set_icon(self, running):
        if self._sf_available and self._nsstatusitem:
            _set_sf_symbol(
                self._nsstatusitem, SF_MIC if running else SF_MIC_SLASH
            )
        else:
            self.title = EMOJI_RUNNING if running else EMOJI_STOPPED

    def _save_and_notify(self):
        self.config.save()
        if is_daemon_running():
            rumps.notification(
                "claude-stt",
                "Settings saved",
                "Restart daemon to apply changes.",
                sound=False,
            )

    # ── Lifecycle ────────────────────────────────────────────

    @rumps.timer(0.1)
    def _initial_setup(self, timer):
        """Apply SF Symbol icons after Cocoa app is fully initialized."""
        timer.stop()
        try:
            self._nsstatusitem = self._nsapp.nsstatusitem
            if _set_sf_symbol(self._nsstatusitem, SF_MIC_SLASH):
                self._sf_available = True
                self.title = ""
        except Exception:
            logger.debug("SF Symbols unavailable, using emoji", exc_info=True)
        self._update_status()

    @rumps.timer(2)
    def _poll_status(self, _timer):
        self._update_status()

    def _update_status(self):
        running = is_daemon_running()
        self._set_icon(running)

        if running:
            self._status_item.title = "Status: Running"
            self._toggle_daemon.title = "Stop Daemon"
            self._toggle_record.set_callback(self._on_toggle_recording)
        else:
            self._status_item.title = "Status: Stopped"
            self._toggle_daemon.title = "Start Daemon"
            self._toggle_record.set_callback(None)

        # Sync config display
        self.config = Config.load().validate()
        self._hotkey_item.title = f"Hotkey: {self.config.hotkey}"
        self._lang_item.title = (
            f"Language: {self.config.language or 'auto'}"
        )
        self._sound_item.state = self.config.sound_effects
        self._update_mode_checks()
        self._engine_item.title = f"Engine: {self._engine_label()}"

    # ── Daemon control ───────────────────────────────────────

    def _on_toggle_daemon(self, _sender):
        if is_daemon_running():
            stop_daemon()
            rumps.notification(
                "claude-stt", "Daemon stopped", "", sound=False
            )
        else:
            threading.Thread(
                target=lambda: start_daemon(background=True), daemon=True
            ).start()
            rumps.notification(
                "claude-stt", "Starting daemon...", "", sound=False
            )
        time.sleep(0.5)
        self._update_status()

    def _on_toggle_recording(self, _sender):
        if not is_daemon_running():
            return
        if not toggle_recording():
            rumps.notification(
                "claude-stt",
                "Toggle failed",
                "Could not send signal to daemon.",
                sound=False,
            )

    def _on_restart_daemon(self, _sender):
        if is_daemon_running():
            stop_daemon()
            time.sleep(1)
        threading.Thread(
            target=lambda: start_daemon(background=True), daemon=True
        ).start()
        rumps.notification(
            "claude-stt", "Restarting daemon...", "", sound=False
        )
        time.sleep(1)
        self._update_status()

    # ── Settings dialogs ─────────────────────────────────────

    def _on_edit_hotkey(self, _sender):
        w = rumps.Window(
            message="Enter the hotkey combination (e.g. cmd_r, ctrl+shift+space):",
            title="Edit Hotkey",
            default_text=self.config.hotkey,
            ok="Save",
            cancel="Cancel",
        )
        response = w.run()
        if response.clicked and response.text.strip():
            self.config.hotkey = response.text.strip()
            self._save_and_notify()

    def _on_set_mode_ptt(self, _sender):
        self.config.mode = "push-to-talk"
        self._update_mode_checks()
        self._save_and_notify()

    def _on_set_mode_toggle(self, _sender):
        self.config.mode = "toggle"
        self._update_mode_checks()
        self._save_and_notify()

    def _on_edit_language(self, _sender):
        w = rumps.Window(
            message="Language code for transcription (e.g. de, en, fr).\nLeave empty for auto-detect:",
            title="Edit Language",
            default_text=self.config.language or "",
            ok="Save",
            cancel="Cancel",
        )
        response = w.run()
        if response.clicked:
            val = response.text.strip() or None
            self.config.language = val
            self._save_and_notify()

    def _on_edit_vocab(self, _sender):
        w = rumps.Window(
            message="Domain vocabulary helps the model recognize project names,\ntechnical terms, and proper nouns.\n\nComma-separated list:",
            title="Edit Vocabulary",
            default_text=self.config.initial_prompt or "",
            ok="Save",
            cancel="Cancel",
            dimensions=(480, 120),
        )
        response = w.run()
        if response.clicked:
            val = response.text.strip() or None
            self.config.initial_prompt = val
            self._save_and_notify()

    def _on_toggle_sounds(self, _sender):
        self.config.sound_effects = not self.config.sound_effects
        self._sound_item.state = self.config.sound_effects
        self.config.save()

    # ── Utilities ────────────────────────────────────────────

    def _on_open_log(self, _sender):
        log_file = Config.get_config_dir() / "daemon.log"
        if log_file.exists():
            subprocess.run(["open", "-a", "Console", str(log_file)])
        else:
            rumps.notification(
                "claude-stt",
                "No log file",
                str(log_file),
                sound=False,
            )

    def _on_quit(self, _sender):
        if is_daemon_running():
            response = rumps.alert(
                title="Quit claude-stt",
                message="The STT daemon is still running.\nStop it before quitting?",
                ok="Stop & Quit",
                cancel="Quit (keep running)",
            )
            if response == 1:
                stop_daemon()
        rumps.quit_application()


def run_menubar():
    """Entry point for the menu bar app."""
    if rumps is None:
        print("rumps is not installed. Install with: pip install rumps")
        raise SystemExit(1)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = STTMenuBarApp()
    app.run()
