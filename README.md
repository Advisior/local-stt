# Local-STT

Free, local, private speech-to-text for your Mac. No cloud, no API costs, no data leaves your device.

![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)
![Platform](https://img.shields.io/badge/Platform-macOS_(Apple_Silicon)-blue.svg)
![GitHub release](https://img.shields.io/github/v/release/Advisior/local-stt?include_prereleases)

> Hold right CMD, speak, release — text appears at your cursor. Works in any app.

<!-- TODO: Replace with actual screenshots of menu bar app + settings -->
<!-- ![Local-STT Menu Bar](docs/screenshots/menubar.png) -->
<!-- ![Local-STT Settings](docs/screenshots/settings.png) -->

---

## Features

| | Feature | Details |
|---|---------|---------|
| 🎙️ | **Native Menu Bar App** | Always-on macOS status bar control with popover UI |
| 🔒 | **100% Local** | MLX Whisper runs on Apple Silicon GPU — no cloud, no API keys |
| ⚡ | **Fast** | ~2-3s transcription (medium model) on M-series chips |
| 🇩🇪 | **14 Languages** | German, English, French, Spanish, and 10 more |
| ⌨️ | **Push-to-Talk** | Hold right CMD (or any configurable hotkey), speak, release |
| 🎛️ | **Settings UI** | Native SwiftUI settings with hotkey recorder, engine picker, vocabulary editor |
| 🔊 | **Sound Feedback** | Audio cues for recording start/stop |
| 📝 | **Custom Vocabulary** | Add domain-specific terms to improve recognition accuracy |

---

## Download

Download the latest release from the [Releases page](https://github.com/Advisior/local-stt/releases).

Or build from source (see [Development](#development) below).

---

## Quick Start

### 1. Install Python dependencies

```bash
git clone https://github.com/Advisior/local-stt.git
cd local-stt

python3.12 -m venv .venv    # Python 3.11, 3.12, or 3.13
source .venv/bin/activate

pip install -e .
pip install mlx-whisper
```

### 2. Configure

```bash
mkdir -p ~/.claude/plugins/claude-stt

cat > ~/.claude/plugins/claude-stt/config.toml << 'EOF'
[claude-stt]
hotkey = "cmd_r"
mode = "push-to-talk"
engine = "mlx"
whisper_model = "medium"
sample_rate = 16000
max_recording_seconds = 300
output_mode = "auto"
sound_effects = true
language = "de"
initial_prompt = "TypeScript, React, Node.js, PostgreSQL, Docker, Kubernetes, GitHub Actions, REST API, GraphQL, WebSocket"
EOF
```

### 3. Build and install the menu bar app

```bash
bash scripts/build-app.sh
bash scripts/install-app.sh
```

### 4. Start

Launch **Local-STT** from `/Applications` or start the daemon via CLI:

```bash
claude-stt start
```

Grant microphone access when macOS prompts you.

---

## Menu Bar App

The menu bar app lives in your status bar and provides quick access to all controls:

- **Status indicator** — green dot when running, red when stopped
- **Start/Stop** daemon with one click
- **Toggle Recording** (or use your hotkey)
- **Settings** — full configuration UI
- **Open Log** — quick access to daemon logs

### Settings

Three tabs for full control:

**General** — Hotkey recorder (click and press your key), recording mode (push-to-talk vs toggle), engine selection (MLX Whisper, Whisper, Moonshine), model size

**Transcription** — Language selection with country flags, custom vocabulary editor with character counter

**About** — Daemon status, version info, project links

---

## Engines

| Engine | Best for | Speed | Models |
|--------|----------|-------|--------|
| **MLX Whisper** (recommended) | Apple Silicon Macs | ~2-3s (medium) | tiny, base, small, **medium**, large, large-v3, large-v3-turbo |
| **Whisper** | CPU-based fallback | ~5-8s (medium) | Same as MLX |
| **Moonshine** | Fastest, English-only | ~0.4s | tiny, base |

MLX Whisper uses 4-bit quantized models optimized for M-series chips. The medium model (~1.5 GB, downloaded once) is the best balance of speed and accuracy for German.

---

## Configuration

Settings are stored in `~/.claude/plugins/claude-stt/config.toml` and can be edited via the Settings UI or directly.

| Option | Default | Description |
|--------|---------|-------------|
| `hotkey` | `cmd_r` | Recording trigger key. Side-specific: `cmd_r`, `cmd_l`, `shift_l`, `alt_r`, etc. |
| `mode` | `push-to-talk` | `push-to-talk` (hold to record) or `toggle` (press to start/stop) |
| `engine` | `mlx` | STT engine: `mlx`, `whisper`, `moonshine` |
| `whisper_model` | `medium` | Model size: `tiny`, `base`, `small`, `medium`, `large`, `large-v3`, `large-v3-turbo` |
| `language` | `de` | Recognition language (2-letter code) or omit for auto-detect |
| `initial_prompt` | — | Comma-separated vocabulary terms to improve recognition |
| `sound_effects` | `true` | Audio feedback on recording start/stop |
| `output_mode` | `auto` | Text insertion: `auto`, `injection` (keyboard), `clipboard` |
| `max_recording_seconds` | `300` | Maximum recording duration in seconds |

### Custom Vocabulary

The `initial_prompt` tells Whisper which domain-specific terms you use. This dramatically improves recognition of technical words:

```toml
initial_prompt = "TypeScript, React, Kubernetes, PostgreSQL, GraphQL, WebSocket, CI/CD Pipeline, OAuth, Terraform"
```

Keep it under ~500 characters. Only add terms that Whisper would otherwise misspell.

---

## CLI Commands

```bash
claude-stt start     # Start the STT daemon
claude-stt stop      # Stop the daemon
claude-stt status    # Show daemon status
claude-stt setup     # First-time setup wizard
claude-stt menubar   # Launch the menu bar app
```

---

## Requirements

- macOS with **Apple Silicon** (M1/M2/M3/M4/M5)
- **Python 3.11-3.13**
- ~1.5 GB disk for the Whisper medium model (downloaded once)

### Required Permissions

Local-STT needs three macOS permissions to function. The app requests them automatically on first start — you'll see three system dialogs in sequence:

1. **Microphone** — "Local-STT would like to access the microphone." Click **OK** to allow audio capture for speech recognition.

2. **Accessibility** — "Local-STT would like to control this computer using accessibility features." Click **Open System Settings**, then enable the toggle for Local-STT. This is required for global hotkey detection.

3. **System Events / Automation** — "Local-STT wants access to control System Events." Click **OK** to allow text injection into the active window.

| Permission | Why | Where to grant |
|------------|-----|----------------|
| **Microphone** | Audio capture for speech recognition | System Settings > Privacy & Security > Microphone |
| **Accessibility** | Global hotkey detection (pynput) | System Settings > Privacy & Security > Accessibility |
| **Input Monitoring** | Keyboard event monitoring | System Settings > Privacy & Security > Input Monitoring |

**Important:** After granting Accessibility access, **restart the daemon** (Stop + Start in the menu bar) for the permission to take effect.

> The STT model is downloaded once from HuggingFace (~1.5 GB). After that, all processing is 100% offline — no network requests on subsequent starts.

> **Linux/Windows:** The Python daemon works cross-platform, but the native menu bar app is macOS-only. See the [CLI Commands](#cli-commands) for cross-platform usage.

---

## Uninstall

```bash
bash scripts/uninstall-app.sh
```

This removes the app, stops the daemon, and cleans up all macOS permissions (Microphone, Accessibility, Input Monitoring). Config files and the model cache are kept — the script shows how to remove them manually.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| No sound on key press | System Settings > Privacy & Security > Microphone > your terminal app |
| "No speech detected" (-93 dB) | Check mic input level in System Settings > Sound > Input |
| Wrong language output | Set `language = "de"` (or your language code) in config |
| Slow transcription | Switch to `small` model, or ensure no other GPU tasks running |
| Hotkey doesn't work | Quit other STT tools that capture the same key |
| Python version error | Use Python 3.11-3.13: `python3.12 -m venv .venv` |
| "pynput unavailable" | Grant Accessibility: System Settings > Privacy & Security > Accessibility > your terminal |

### Logs

```bash
tail -f /tmp/claude-stt.log
```

---

## Privacy

**All processing happens on your device.** No audio, no text, no telemetry is ever sent anywhere.

- Audio captured from your microphone is processed entirely on-device
- MLX Whisper runs locally on your Apple Silicon GPU
- Audio is processed in memory and immediately discarded
- Transcribed text only goes to the active window or clipboard
- No telemetry, no analytics, no tracking

---

## Development

```bash
git clone https://github.com/Advisior/local-stt.git
cd local-stt

# Python daemon
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
python -m unittest discover -s tests

# Lint
ruff check src/

# Build menu bar app
bash scripts/build-app.sh
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on how to get started.

---

## Security

To report a security vulnerability, please see [SECURITY.md](SECURITY.md). Do not open public issues for security reports.

---

## Acknowledgments

Originally created by [Jarrod Watts](https://github.com/jarrodwatts). Fork maintained and extended by [Advisior GmbH](https://www.advisior.de).

---

## License

MIT — see [LICENSE](LICENSE)
