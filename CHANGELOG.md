# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- Native macOS menu bar app with SwiftUI settings panel
- Hotkey recorder with system shortcut conflict detection
- Engine selection dropdown (MLX Whisper, Whisper, Moonshine)
- Language dropdown with 14 languages and country flags
- Vocabulary character counter
- About tab with status card and project links

### Security
- File permission enforcement on config and PID files (0600/0700)
- Log sanitization for transcribed text (PII protection)
- AppleScript escaping hardened against injection
- Input validation on all configuration values

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
