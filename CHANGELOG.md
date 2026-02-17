# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

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
