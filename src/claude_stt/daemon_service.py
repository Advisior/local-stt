"""Runtime daemon service for claude-stt."""

from __future__ import annotations

import logging
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from typing import Optional

import numpy as np

from .config import Config
from .engine_factory import build_engine
from .formatter import fix_transcription_errors, format_paragraphs
from .engines import STTEngine
from .errors import EngineError, HotkeyError, RecorderError
from .hotkey import HotkeyListener
from .keyboard import output_text
from .recorder import AudioRecorder, RecorderConfig
from .sounds import play_sound
from .window import get_active_window, WindowInfo


class STTDaemon:
    """Main daemon that coordinates all STT components."""

    def __init__(self, config: Optional[Config] = None):
        """Initialize the daemon.

        Args:
            config: Configuration, or load from file if None.
        """
        self.config = (config or Config.load()).validate()
        self._running = False
        self._recording = False

        # Components
        self._recorder: Optional[AudioRecorder] = None
        self._engine: Optional[STTEngine] = None
        self._hotkey: Optional[HotkeyListener] = None

        # Recording state
        self._record_start_time: float = 0
        self._last_duration_s: float = 0.0
        self._original_window: Optional[WindowInfo] = None
        self._pre_record_volume: int | None = None
        # Overlay subprocess
        self._overlay_proc: Optional[subprocess.Popen] = None
        # Threading
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._transcribe_queue: "queue.Queue[Optional[tuple[object, Optional[WindowInfo]]]]" = (
            queue.Queue(maxsize=2)
        )
        self._transcribe_thread: Optional[threading.Thread] = None
        self._logger = logging.getLogger(__name__)

    def _start_overlay(self) -> None:
        """Start the overlay indicator subprocess."""
        try:
            overlay_module = os.path.join(
                os.path.dirname(__file__), "overlay.py"
            )
            self._overlay_proc = subprocess.Popen(
                [sys.executable, overlay_module],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._logger.info("Overlay indicator started (PID %d)", self._overlay_proc.pid)
        except Exception:
            self._logger.debug("Overlay indicator not available", exc_info=True)
            self._overlay_proc = None

    def _overlay_send(self, command: str) -> None:
        """Send a command to the overlay subprocess."""
        if self._overlay_proc and self._overlay_proc.poll() is None:
            try:
                self._overlay_proc.stdin.write((command + "\n").encode())
                self._overlay_proc.stdin.flush()
            except (BrokenPipeError, OSError):
                self._overlay_proc = None

    def _stop_overlay(self) -> None:
        """Stop the overlay subprocess."""
        if self._overlay_proc and self._overlay_proc.poll() is None:
            self._overlay_send("QUIT")
            try:
                self._overlay_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._overlay_proc.kill()
            self._overlay_proc = None

    def _init_components(self) -> bool:
        """Initialize all components.

        Returns:
            True if all components initialized successfully.
        """
        try:
            self._recorder = AudioRecorder(
                RecorderConfig(
                    sample_rate=self.config.sample_rate,
                    max_recording_seconds=self.config.max_recording_seconds,
                    device=self.config.audio_device,
                )
            )
            if not self._recorder.is_available():
                raise RecorderError("No audio input device available")

            # Log audio device
            try:
                import sounddevice as sd
                if self.config.audio_device is not None:
                    device_info = sd.query_devices(self.config.audio_device)
                    self._logger.info("Audio input: [%s] %s", self.config.audio_device, device_info['name'])
                else:
                    device_info = sd.query_devices(kind='input')
                    self._logger.info("Audio input: %s (default)", device_info['name'])
            except Exception:
                pass

            self._engine = build_engine(self.config)
            if not self._engine.is_available():
                raise EngineError(
                    "STT engine not available. Run setup to install dependencies."
                )

            self._hotkey = HotkeyListener(
                hotkey=self.config.hotkey,
                on_start=self._on_recording_start,
                on_stop=self._on_recording_stop,
                mode=self.config.mode,
            )
        except (RecorderError, EngineError, HotkeyError) as exc:
            self._logger.error("%s", exc)
            return False

        self._start_transcription_worker()
        return True

    def _start_transcription_worker(self) -> None:
        if self._transcribe_thread is not None:
            return

        self._transcribe_thread = threading.Thread(
            target=self._transcribe_worker,
            name="claude-stt-transcribe",
            daemon=True,
        )
        self._transcribe_thread.start()

    def _transcribe_worker(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._transcribe_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if item is None:
                break

            audio, window_info = item
            if not self._engine:
                continue

            # Log audio level
            rms = np.sqrt(np.mean(audio**2))
            db = 20 * np.log10(max(rms, 1e-10))
            if db < self.config.min_audio_db:
                self._logger.info(
                    "Skipping: audio too quiet (%.1f dB < %.1f dB threshold)",
                    db, self.config.min_audio_db,
                )
                self._overlay_send("CANCEL")
                continue
            self._logger.info("Transcribing audio (%d samples, %.1f dB)...", len(audio), db)
            try:
                text = self._engine.transcribe(audio, self.config.sample_rate)
            except Exception:
                self._logger.exception("Transcription failed")
                self._overlay_send("CANCEL")
                continue

            text = text.strip()
            if not text:
                self._logger.info("No speech detected")
                if self.config.sound_effects:
                    play_sound("warning")
                self._overlay_send("CANCEL")
                continue

            # Fix common mis-transcriptions, then format paragraphs
            text = fix_transcription_errors(text, self.config.corrections)
            text = format_paragraphs(text)

            word_count = len(text.split())
            preview = text[:120].replace("\n", " ")
            self._logger.info("Transcribed %d words: %r", word_count, preview)
            if not output_text(text, window_info, self.config):
                self._logger.warning("Failed to output transcription")
            self._append_history(text, self._last_duration_s, db)
            self._overlay_send(f"DONE {word_count}")

    def _append_history(self, text: str, duration_s: float, db: float) -> None:
        """Append transcription to history file, keeping last 100 entries."""
        import json
        from datetime import datetime
        history_path = Config.get_config_dir() / "history.jsonl"
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "text": text,
            "duration_s": round(duration_s, 1),
            "db": round(db, 1),
            "words": len(text.split()),
        }
        entries = []
        if history_path.exists():
            try:
                entries = [json.loads(line) for line in history_path.read_text().splitlines() if line.strip()]
            except Exception:
                entries = []
        entries.append(entry)
        entries = entries[-100:]
        history_path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    def _mute_system_audio(self) -> None:
        """Mute system output and store original volume for restore."""
        try:
            result = subprocess.run(
                ["osascript", "-e", "output volume of (get volume settings)"],
                capture_output=True, text=True, timeout=1,
            )
            self._pre_record_volume = int(result.stdout.strip())
            subprocess.run(
                ["osascript", "-e", "set volume output muted true"],
                capture_output=True, timeout=1,
            )
        except Exception:
            self._logger.debug("Failed to mute system audio", exc_info=True)
            self._pre_record_volume = None

    def _restore_system_audio(self) -> None:
        """Restore system output volume after recording."""
        if self._pre_record_volume is None:
            return
        try:
            subprocess.run(
                ["osascript", "-e", f"set volume output volume {self._pre_record_volume}"],
                capture_output=True, timeout=1,
            )
            subprocess.run(
                ["osascript", "-e", "set volume output muted false"],
                capture_output=True, timeout=1,
            )
        except Exception:
            self._logger.debug("Failed to restore system audio", exc_info=True)
        finally:
            self._pre_record_volume = None

    def _on_recording_start(self):
        """Called when recording should start."""
        with self._lock:
            if self._recording:
                return

            self._recording = True
            if self.config.mute_on_record:
                self._mute_system_audio()
            self._record_start_time = time.time()

            # Capture the active window
            self._original_window = get_active_window()

            # Start recording
            if self._recorder and self._recorder.start():
                self._logger.info("Recording started")
                if self.config.sound_effects:
                    play_sound("start")
                self._overlay_send("RECORDING")
            else:
                self._logger.error("Audio recorder failed to start")
                self._recording = False
                if self.config.sound_effects:
                    play_sound("error")

    def _on_recording_stop(self):
        """Called when recording should stop."""
        audio = None
        window_info = None
        with self._lock:
            if not self._recording:
                return

            self._recording = False
            if self.config.mute_on_record:
                self._restore_system_audio()
            elapsed = time.time() - self._record_start_time
            self._last_duration_s = elapsed

            if elapsed < self.config.min_recording_seconds:
                self._logger.info(
                    "Skipping: recording too short (%.1fs < %.1fs threshold)",
                    elapsed, self.config.min_recording_seconds,
                )
                self._overlay_send("CANCEL")
                return

            # Stop recording
            if self._recorder:
                audio = self._recorder.stop()
            window_info = self._original_window

            self._logger.info("Recording stopped (%.1fs)", elapsed)
            if self.config.sound_effects:
                play_sound("stop")
            self._overlay_send("TRANSCRIBING")

        # Transcribe outside the lock
        if audio is not None and len(audio) > 0:
            try:
                self._transcribe_queue.put_nowait((audio, window_info))
            except queue.Full:
                self._logger.warning("Dropping transcription; queue is full")
                self._overlay_send("CANCEL")
        else:
            # No audio captured — cancel the transcribing indicator
            self._overlay_send("CANCEL")
            if self.config.sound_effects:
                play_sound("warning")

    def _check_max_recording_time(self) -> None:
        """Check if max recording time has been reached."""
        if not self._recording:
            return

        elapsed = time.time() - self._record_start_time
        max_seconds = self.config.max_recording_seconds

        # Warning at 30 seconds before max
        if max_seconds > 30 and max_seconds - 30 <= elapsed < max_seconds - 29:
            if self.config.sound_effects:
                play_sound("warning")

        if elapsed >= max_seconds:
            self._on_recording_stop()

    def run(self):
        """Run the daemon main loop."""
        self._logger.info("claude-stt daemon starting...")
        self._logger.info("Hotkey: %s", self.config.hotkey)
        self._logger.info("Engine: %s", self.config.engine)
        self._logger.info("Mode: %s", self.config.mode)

        if not self._init_components():
            raise SystemExit(1)

        # Load the model
        self._logger.info("Loading STT model...")
        if not self._engine.load_model():
            self._logger.error("Failed to load STT model")
            raise SystemExit(1)

        self._logger.info("Model loaded. Ready for voice input.")

        # Start overlay indicator
        self._start_overlay()

        # Start hotkey listener
        if not self._hotkey.start():
            self._logger.error("Failed to start hotkey listener")
            raise SystemExit(1)

        self._running = True

        # Handle shutdown signals
        def shutdown(signum, frame):
            self._logger.info("Shutting down...")
            self._running = False

        def toggle_recording(signum, frame):
            if self._recording:
                self._logger.info("SIGUSR1: stopping recording")
                self._on_recording_stop()
            else:
                self._logger.info("SIGUSR1: starting recording")
                self._on_recording_start()

        try:
            signal.signal(signal.SIGINT, shutdown)
            signal.signal(signal.SIGTERM, shutdown)
            if hasattr(signal, "SIGUSR1"):
                signal.signal(signal.SIGUSR1, toggle_recording)
            else:
                self._logger.debug("SIGUSR1 not supported on this platform")
        except Exception:
            self._logger.debug("Signal handlers unavailable", exc_info=True)

        # Main loop
        try:
            while self._running:
                self._check_max_recording_time()
                time.sleep(0.1)
        finally:
            self.stop()

    def stop(self):
        """Stop the daemon."""
        self._running = False
        self._stop_event.set()

        try:
            self._transcribe_queue.put_nowait(None)
        except queue.Full:
            pass

        if self._transcribe_thread:
            self._transcribe_thread.join(timeout=1.0)
            if self._transcribe_thread.is_alive():
                self._logger.warning("Transcribe thread did not exit cleanly")

        if self._recording and self._recorder:
            self._recorder.stop()

        if self._hotkey:
            self._hotkey.stop()

        self._stop_overlay()

        self._logger.info("claude-stt daemon stopped.")
