# Claude STT - Local Voice Input for Claude Code

Free, local, private speech-to-text for Claude Code on Apple Silicon. No cloud, no API costs, no data leaves your Mac.

**What you get:** Hold right CMD key, speak German (or any language), release - text appears at your cursor. Works in any app.

## Requirements

- macOS with Apple Silicon (M1/M2/M3/M4/M5)
- Python 3.10-3.13 (not 3.14+)
- ~1.5 GB disk for the Whisper medium model (downloaded once)
- Microphone access granted to your terminal app

## Quick Setup (5 minutes)

```bash
# 1. Clone
git clone https://github.com/jarrodwatts/claude-stt.git
cd claude-stt

# 2. Create venv with compatible Python
python3.12 -m venv .venv   # or python3.11, python3.13
source .venv/bin/activate

# 3. Install with MLX support
pip install -e .
pip install mlx-whisper

# 4. Create config directory
mkdir -p ~/.claude/plugins/claude-stt

# 5. Write config
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
initial_prompt = "TypeScript, React, Node.js, PostgreSQL, Docker, Kubernetes, GitHub Actions, REST API, GraphQL, WebSocket, Microservices, CI/CD Pipeline"
EOF

# 6. Grant microphone access
# macOS will prompt on first run - click "Allow"

# 7. Start
claude-stt start
```

## Customizing Your Vocabulary

The `initial_prompt` in the config tells Whisper which domain-specific terms you use. This dramatically improves recognition of technical words.

Edit `~/.claude/plugins/claude-stt/config.toml` and replace the `initial_prompt` with your own terms:

### Examples by Domain

**Web Development:**
```toml
initial_prompt = "TypeScript, React, Next.js, Tailwind CSS, Prisma, tRPC, Zustand, Vite, ESLint, Prettier, Vercel, Supabase, PostgreSQL, Redis, Docker, Kubernetes, GitHub Actions, CI/CD Pipeline, REST API, GraphQL, WebSocket"
```

**Data Science / ML:**
```toml
initial_prompt = "Python, Jupyter, pandas, NumPy, scikit-learn, TensorFlow, PyTorch, Matplotlib, Hugging Face, Transformers, CUDA, MLflow, Feature Engineering, Hyperparameter Tuning, Random Forest, Gradient Boosting, Neural Network"
```

**DevOps / Infrastructure:**
```toml
initial_prompt = "Terraform, Ansible, Kubernetes, Helm, ArgoCD, Prometheus, Grafana, Docker Compose, nginx, Caddy, Let's Encrypt, Hetzner, AWS, CloudFlare, GitHub Actions, GitLab CI, SonarQube, Vault, Consul"
```

**Finance / Banking:**
```toml
initial_prompt = "MiFID, DSGVO, KYC, AML, PSD2, SWIFT, SEPA, BaFin, Atruvia, DZ Bank, Consors Bank, UniCredit, Bloomberg, Reuters, Portfolio, Derivate, Hedging, Compliance, Risikomanagement"
```

**Custom - mix your own:**
```toml
initial_prompt = "YourCompany, ProjectAlpha, SpecialTool, CustomFramework, TeamName, ProductName"
```

### Tips for initial_prompt

- Keep it under ~500 characters (Whisper truncates at ~224 tokens)
- List proper nouns and technical terms that Whisper would otherwise misspell
- Comma-separated list is most token-efficient
- No need to include common words - only specialized vocabulary

## Language

Change `language` in the config:

| Language | Code |
|----------|------|
| German | `de` |
| English | `en` |
| French | `fr` |
| Spanish | `es` |
| Auto-detect | Remove the `language` line |

## Hotkey Options

Edit `hotkey` and `mode` in the config:

| Setup | hotkey | mode | Usage |
|-------|--------|------|-------|
| **Right CMD (recommended)** | `cmd_r` | `push-to-talk` | Hold to speak, release to transcribe |
| Right CMD toggle | `cmd_r` | `toggle` | Press to start, press again to stop |
| Keyboard shortcut | `ctrl+shift+d` | `toggle` | Press combo to start/stop |
| Left Alt | `alt_l` | `push-to-talk` | Hold left Alt to speak |

**Side-specific keys:** `cmd_r`, `cmd_l`, `ctrl_r`, `ctrl_l`, `shift_r`, `shift_l`, `alt_r`, `alt_l`

## Model Sizes

Edit `whisper_model` in the config:

| Model | Size | Speed (M1) | Quality | Best for |
|-------|------|------------|---------|----------|
| `tiny` | ~75 MB | ~0.5s | Low | Quick tests |
| `base` | ~150 MB | ~0.8s | OK | English-only, speed priority |
| `small` | ~500 MB | ~1.5s | Good | Multilingual, balanced |
| **`medium`** | ~1.5 GB | ~2-3s | **Great** | **Recommended for German** |
| `large-v3` | ~3 GB | ~5-8s | Best | Maximum accuracy |

MLX automatically uses 4-bit quantized models for faster inference.

## Daily Usage

```bash
# Start daemon (runs in background)
claude-stt start

# Check status
claude-stt status

# Stop daemon
claude-stt stop

# Auto-start on login (optional)
# Add to Login Items: System Settings > General > Login Items
# Or create a launchd plist (see below)
```

### Auto-Start on Login

```bash
cat > ~/Library/LaunchAgents/com.claude-stt.daemon.plist << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.claude-stt.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>$(which claude-stt)</string>
        <string>start</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
EOF

launchctl load ~/Library/LaunchAgents/com.claude-stt.daemon.plist
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| No sound on key press | Check: System Settings > Privacy & Security > Microphone > your terminal app |
| "No speech detected" (-93 dB) | Check microphone input level in System Settings > Sound > Input |
| Wrong language output | Add `language = "de"` (or your language code) to config |
| Slow transcription | Switch to `small` model, or ensure no other heavy GPU tasks running |
| Hotkey doesn't work | Quit Wispr Flow or other STT tools that capture the same key |
| Python 3.14 error | Use Python 3.12: `python3.12 -m venv .venv` |
| "pynput unavailable" | Grant Accessibility access: System Settings > Privacy & Security > Accessibility > your terminal |

## Logs

```bash
tail -f /tmp/claude-stt.log
```

Look for:
- `Audio input: Fifine Microphone` - correct mic selected
- `Transcribing audio (... samples, -20.5 dB)` - good signal level (should be -30 to -10 dB)
- `No speech detected` with -90+ dB - mic muted or wrong device
