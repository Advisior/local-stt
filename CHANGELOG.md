# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [0.11.6] - 2026-10-31

### Fixed
- After the input device drops, errors or changes, the next dictation records from the current default input again without restarting Local-STT. A stream that sent no audio for 1 s is closed, PortAudio is re-initialized so it re-reads the device list, and a new stream opens on the configured device or the current default, at recording start and once during a running recording (audio from before the gap is kept). A recording that ended without audio also reopens the stream (#44)
- On macOS the daemon follows changes of the system default input (for example AirPods to built-in mic) within 3 s while idle, unless `audio_device` is set (#44)
- When the reopen fails or the new stream stays silent, the recording ends, the overlay shows "No microphone input. Check the input device.", the error sound plays and `daemon.log` names the device (#44)

## [0.11.2] - 2026-10-31

### Changed
- Internal: the macOS key event intercept moved from `hotkey.py` to `hotkey_darwin.py`, and its tests moved to `tests/test_hotkey_darwin.py`, so both `hotkey.py` and `tests/test_hotkey.py` are below the 500-line limit again. No behavior change (#71)

## [0.11.1] - 2026-10-31

### Fixed
- A hotkey that mixes a generic and a side-specific modifier, such as `ctrl+cmd_r`, now needs every listed key. Before, `ctrl` was dropped and the hotkey fired on `cmd_r` alone. `ctrl` accepts either Control key, `cmd_r` only the right Command key (#70)

## [0.9.3] - 2026-10-23

### Fixed
- macOS: a hotkey ending in a character key (e.g. `ctrl+shift+r`) no longer reaches the focused app. The key's down, auto-repeat and up events are swallowed using the keycode of the actual press, so it works with any keyboard layout (#41)
- macOS: generic modifiers in a hotkey (`ctrl`, `shift`, `alt`, `cmd`) cover both the left and the right key, so completing a combination with the right-hand modifier no longer leaks that key to the app. Side-specific hotkeys such as `cmd_r` still swallow only the named side (#41)
- macOS: modifier events are classified as press or release from the key's own device flag bit. After a lost release, the next press of that modifier is no longer swallowed unless it completes a hotkey again (#41)

## [0.9.0] - 2026-10-20

### Added
- Delete single entries in the Transcript History window. The app and the daemon both lock `history.lock` and replace `history.jsonl` atomically, so a delete and a new dictation at the same moment keep both effects (#47)
- Private mode in the menu bar popover: 15 minutes, 1 hour or until turned off. While it is on, dictations are still typed or pasted but not added to the history, pasteboard writes are marked `org.nspasteboard.ConcealedType` and `TransientType` so clipboard managers skip them, and the menu bar icon changes. The state lives in `private_mode.json` and survives restarts of app and daemon; an unreadable state file counts as on (#47)

### Changed
- `daemon.log` no longer contains any transcript text, only the word count (#47)

## [0.8.1] - 2026-10-20

### Fixed
- MLX short model names `tiny`, `base`, `small`, `medium`, `large` and `large-v3` now point to the existing `mlx-community/whisper-*-mlx` repos. Selecting `large-v3` failed with `RepositoryNotFoundError` and the daemon could not record (#52)

## [0.8.0] - 2026-10-19

### Added
- Optional undo hotkey (`undo_hotkey`, off by default, macOS only) that removes the last dictation insert with one Backspace per character. It only acts within `undo_window_seconds` (default 60), in the same frontmost app, before any other key press, once per insert, and for single-line text up to `undo_max_chars` (default 400) without emoji, zero width joiners or combining marks. Otherwise the overlay shows "Nothing to undo" or "Too long to undo". Its key events are swallowed like the record hotkey's, and the menu bar Settings get a second hotkey recorder for it (#45)
- Hotkey strings accept the named keys the menu bar recorder writes (`backspace`, `delete`, arrow keys, `home`, `end`, `pageup`, `pagedown`) (#45)

## [0.7.0] - 2026-09-25

### Changed
- Fresh installs on Apple Silicon now default to the MLX Whisper engine with the `large-v3-turbo` model instead of the English-only Moonshine engine. Intel Macs, Linux and Windows keep Moonshine, because MLX does not run there. The Python config and the menu bar app use the same defaults. An existing `config.toml` is not changed: it keeps the engine and model it already names (#38)
- `scripts/setup.py` now installs the `mlx` extra on Apple Silicon, so the plugin setup path has the new default engine available, and setup names the `mlx` extra when MLX Whisper dependencies are missing (#38)

## [0.6.1] - 2026-09-23

### Fixed
- Fresh installs can download their speech model again. The menu bar app started the daemon with `HF_HUB_OFFLINE=1` unconditionally, so with an empty model cache every engine failed to load and dictation produced no text. The daemon launcher now checks the local Hugging Face cache without network access and enables offline mode only once the configured model is fully on disk; an `HF_HUB_OFFLINE` set by the caller still wins (#34)
- Hotkey is no longer forwarded to the focused application. The macOS suppression callback was passed to `pynput` as `intercept=`, but `pynput` only collects platform options carrying the `darwin_` prefix and drops everything else without warning, so the whole suppression path was dead code. Every hotkey press reached the frontmost app in addition to starting dictation, e.g. F1 also opened the help dialog in Microsoft Teams. Only the keys of a triggered hotkey are swallowed, from the press that completes the combination until their release, so with `ctrl+shift+space` a plain Space still types (#37)

### Changed
- README now documents the actual defaults (`ctrl+shift+space`, toggle mode, auto-detected language, Moonshine engine), warns that Moonshine is English-only, gives the correct log path and notes that the Command Line Tools alone cannot build the app on macOS 27 (#35)
- CI and release workflows use `actions/checkout@v7` and `actions/setup-python@v7`

## [0.6.0] - 2026-09-21

### Added
- One-command installer (`install.sh`): sets up a self-contained Python environment, builds the menu bar app from source, and installs it, with no manual venv or build steps required (#32)
- `mlx` optional dependency group (`mlx-whisper`) — previously undeclared even though it's the default and recommended engine
- Swift build coverage in CI: `swift build -c release` now runs on every PR, catching compile errors that the Python-only test matrix couldn't see

### Fixed
- `scripts/build-app.sh` now reads the app version from `pyproject.toml` directly instead of importing an installed `claude_stt` package, which silently stamped every clean-checkout build as `0.1.0` (#31)
- `scripts/build-app.sh` now packages a `Local-STT-vX.Y.Z.zip`, and a tag-triggered release workflow attaches it automatically (#30)
- The four version sources (`pyproject.toml`, `claude_stt/__init__.py`, `plugin.json`, `marketplace.json`) had drifted out of sync; `scripts/check-versions.sh` now fails CI if they disagree again (#31)
- Menu bar app now also looks for its Python environment at `~/Library/Application Support/Local-STT/venv`, the portable location `install.sh` always uses, in addition to the existing developer-machine fallback (#32)

## [0.5.1] - 2026-07-15

### Fixed
- `clipboard_paste` no longer destroys images or files in the clipboard: the full NSPasteboard (all items and types) is snapshotted before the transcript is written and restored after the paste keystroke has been consumed. Previously the save/restore used text-only pyperclip, so a copied screenshot was silently lost on every dictation (#25)

## [0.5.0] - 2026-04-01

### Added
- Search/filter in transcript history: live text search with match counter and yellow word highlighting (#16)
- Hot-reload corrections: user-defined corrections now apply immediately without daemon restart (#17)

### Fixed
- `output_mode` setting no longer reset to "auto" when saving corrections in the UI (#18)
- TOML correction keys with non-ASCII characters (e.g. umlauts) now properly quoted (#18)

## [0.4.0] - 2026-03-30

### Added
- Multi-word correction in History: click first word, click last word to extend selection, click selection to open correction popup
- Copy button on each History entry to copy full transcription to clipboard
- Auto-restart recording when first F1 press is too short (mic wakeup delay)

### Fixed
- "Open Log" menu item now opens the correct log file instead of a non-existent path
- Recording no longer silently fails on first press due to mic wakeup artifacts

## [0.3.0] - 2026-03-04

### Added
- `clipboard_paste` output mode: copies transcription to clipboard and sends Cmd+V, more reliable than keystroke injection in apps that drop rapid key events
- `isStarting` state in DaemonManager with spinner indicator in menu popover — shows "Starting..." while daemon initialises instead of incorrectly showing "Stopped"

### Changed
- `output_mode` config now accepts `clipboard_paste` as an additional option (previous options `auto`, `injection`, `clipboard` unchanged)

## [0.2.0] - 2026-02-17

### Added
- Native macOS menu bar app with SwiftUI popover and settings panel
- Hotkey recorder with left/right modifier distinction and system shortcut conflict detection
- Engine selection dropdown (MLX Whisper, Whisper, Moonshine) with Apple Silicon detection
- Language dropdown with 14 languages and country flags
- Vocabulary editor with character counter (1000 char limit)
- About tab with daemon status card, project links, and credits
- Auto-start daemon when app opens (configurable toggle)
- Launch at Login via SMAppService (macOS 13+)
- Stable code signing identity for persistent macOS permissions across rebuilds
- Uninstall script with TCC permission cleanup
- GitHub issue templates (bug report, feature request)
- Pull request template with testing checklist
- CI pipeline with cross-platform testing (macOS, Linux, Windows)
- Ruff linting in CI
- CONTRIBUTING.md, CODE_OF_CONDUCT.md, SUPPORT.md, SECURITY.md

### Changed
- Minimum Python version raised to 3.11 (onnxruntime dropped 3.10 support)
- README rewritten for current project state (menu bar app, MLX Whisper focus)
- Popover hotkey label now reflects actual configured hotkey (was hardcoded)

### Fixed
- Timer thread safety in DaemonManager (main run loop + background I/O)
- Daemon start timeout (30s DispatchGroup prevents indefinite hang)
- Restart race condition (stop completes before start begins)
- Event monitor leak in HotkeyRecorderView (cleanup on resignFirstResponder)
- Popover no longer recreated on every click (just reloads config)
- Log viewer opens correct file path (/tmp/claude-stt.log)
- Uninstall script uses exact process name match (pkill -x)

### Security
- File permission enforcement on config and PID files (0600/0700)
- Atomic file permissions: chmod before rename to close brief permission window
- Log sanitization for transcribed text (PII protection)
- AppleScript escaping hardened against injection
- PowerShell injection prevention in Windows process lookup
- Input validation on all configuration values
- TOML None-value serialization fix

## [0.1.0] - 2026-01-14

### Added
- Initial open source release
- Moonshine and Whisper STT engines
- MLX Whisper engine for Apple Silicon
- Push-to-talk and toggle recording modes
- Cross-platform support (macOS, Linux, Windows)
- Side-specific hotkey support (left/right modifier keys)
- German language optimization with vocabulary customization
- macOS overlay indicator during recording
- Automatic text input via keyboard injection or clipboard fallback
- Configuration via TOML file
- Claude Code plugin integration
