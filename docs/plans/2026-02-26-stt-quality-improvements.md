# STT Quality Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix garbage/English output under CPU load and short accidental recordings by upgrading the MLX model, adding transcript logging, and hardening the audio pipeline.

**Architecture:** Four independent improvements to `mlx_engine.py`, `daemon_service.py`, `config.py`, and `config.toml`. No breaking changes — all new config keys have safe defaults. Model switch requires ~1.5 GB download on first run.

**Tech Stack:** Python, MLX Whisper (`mlx-community/whisper-large-v3-turbo`), TOML config

---

## Root Cause Summary

From log analysis (`~/.claude/plugins/claude-stt/daemon.log`):

1. **CPU-load degradation** — inference speed drops from 2700 fps to 17 fps under load → Whisper hallucinates in English (English bias from training data)
2. **No transcript logging** — "Transcribed N words" tells us nothing; impossible to debug what's being output
3. **Short/silent clips processed** — 0.3–0.8s at −75 to −86 dB trigger transcription, produce garbage
4. **Model `medium` fragile under load** — `large-v3-turbo` is faster AND better quality for German

---

## Task 1: Add Transcript Logging

**Why:** Without seeing what's actually transcribed, debugging is blind.

**Files:**
- Modify: `src/claude_stt/daemon_service.py` (one line, in `_transcribe_worker`)

**Step 1: Locate the log line for word count**

In `_transcribe_worker`, find:
```python
word_count = len(text.split())
self._logger.info("Transcribed %d words", word_count)
```

**Step 2: Add transcript preview line directly above it**

```python
word_count = len(text.split())
# Log first 120 chars for debugging (full text visible in DEBUG level)
preview = text[:120].replace("\n", " ")
self._logger.info("Transcribed %d words: %r", word_count, preview)
```

**Step 3: Restart daemon and verify in log**

```bash
local-stt stop && local-stt start
tail -f ~/.claude/plugins/claude-stt/daemon.log
```

Say something → log should now show the actual text, e.g.:
```
INFO claude_stt.daemon_service: Transcribed 8 words: 'Hallo, das ist ein Test für das System.'
```

**Step 4: Commit**

```bash
cd /Users/uwefranke/Development/claude-stt
git add src/claude_stt/daemon_service.py
git commit -m "feat: log transcript preview for debuggability"
```

---

## Task 2: Minimum Duration + Minimum dB Guard

**Why:** 0.3–0.8s recordings at −75 to −86 dB are accidental key presses or near-silence. They waste inference time and produce hallucinations.

**Files:**
- Modify: `src/claude_stt/config.py` (add two fields)
- Modify: `src/claude_stt/daemon_service.py` (add guard in `_on_recording_stop`)
- Modify: `~/.claude/plugins/claude-stt/config.toml` (set values)

**Step 1: Add config fields to `Config` dataclass in `config.py`**

After `max_recording_seconds: int = 300`, add:

```python
min_recording_seconds: float = 0.8   # ignore recordings shorter than this
min_audio_db: float = -55.0           # ignore recordings quieter than this
```

**Step 2: Load the new fields in `Config.load()` in `config.py`**

In the `config = cls(...)` block, add the two new fields:

```python
min_recording_seconds=stt_config.get("min_recording_seconds", cls.min_recording_seconds),
min_audio_db=stt_config.get("min_audio_db", cls.min_audio_db),
```

**Step 3: Save the new fields in `Config.save()` in `config.py`**

In the `section = {...}` dict, add:

```python
"min_recording_seconds": self.min_recording_seconds,
"min_audio_db": self.min_audio_db,
```

**Step 4: Add guard in `_transcribe_worker` in `daemon_service.py`**

After the dB calculation (`db = 20 * np.log10(...)`), add:

```python
# Guard: skip near-silence recordings
if db < self.config.min_audio_db:
    self._logger.info(
        "Skipping: audio too quiet (%.1f dB < %.1f dB threshold)",
        db, self.config.min_audio_db,
    )
    self._overlay_send("CANCEL")
    continue
```

**Step 5: Add duration guard in `_on_recording_stop` in `daemon_service.py`**

After `elapsed = time.time() - self._record_start_time`, add:

```python
if elapsed < self.config.min_recording_seconds:
    self._logger.info(
        "Skipping: recording too short (%.1fs < %.1fs threshold)",
        elapsed, self.config.min_recording_seconds,
    )
    self._overlay_send("CANCEL")
    return
```

**Step 6: Set values in config.toml**

In `~/.claude/plugins/claude-stt/config.toml`, under `[claude-stt]`, add:

```toml
min_recording_seconds = 0.8
min_audio_db = -55.0
```

**Step 7: Test**

```bash
local-stt stop && local-stt start
tail -f ~/.claude/plugins/claude-stt/daemon.log
```

- Tap hotkey briefly (< 0.8s) → log: `Skipping: recording too short`
- Tap hotkey without speaking → log: `Skipping: audio too quiet`

**Step 8: Commit**

```bash
cd /Users/uwefranke/Development/claude-stt
git add src/claude_stt/config.py src/claude_stt/daemon_service.py
git commit -m "feat: add min_recording_seconds and min_audio_db guards"
```

---

## Task 3: Upgrade Model to large-v3-turbo

**Why:** `large-v3-turbo` is specifically distilled for Apple Silicon speed. Benchmarks: similar speed to `medium`, 40% better German WER, much more robust under CPU load.

**This task is a config change only — no code changes needed.**

**Model map already in `mlx_engine.py`:**
```python
"large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
```

**Step 1: Update config.toml**

In `~/.claude/plugins/claude-stt/config.toml`, change:

```toml
whisper_model = "large-v3-turbo"
```

**Step 2: Restart daemon (triggers model download ~1.5 GB, one-time)**

```bash
local-stt stop && local-stt start
tail -f ~/.claude/plugins/claude-stt/daemon.log
```

Watch for:
```
Loading MLX Whisper model: mlx-community/whisper-large-v3-turbo
Model loaded. Ready for voice input.
```

First start may take 30–60s for download. Subsequent starts: < 2s.

**Step 3: Test German accuracy**

Say a sentence with project names: "Ich arbeite heute an Tradvisior und Cotedo."

Log should show the correct German text, not English garbage.

**Note:** No commit needed — config.toml is not version-controlled (it's in `~/.claude/plugins/`).

---

## Task 4: Harden MLX Engine Parameters

**Why:** `temperature=0` (greedy decoding) is faster and more deterministic than the default fallback chain. `task="transcribe"` prevents accidental translation mode. Together they reduce the chance of English output.

**Files:**
- Modify: `src/claude_stt/engines/mlx_engine.py`

**Step 1: Add parameters to `kwargs` in `transcribe()` method**

Find the `kwargs = {...}` block. Add these three entries:

```python
kwargs = {
    "path_or_hf_repo": self._hf_repo,
    "verbose": False,
    "compression_ratio_threshold": 2.4,
    "no_speech_threshold": 0.6,
    "condition_on_previous_text": False,
    # New: stable, fast decoding
    "task": "transcribe",        # never translate, always transcribe
    "temperature": 0,            # greedy — no temperature fallback chain
    "word_timestamps": False,    # skip token-level timestamps (faster)
}
```

**Step 2: Restart daemon and verify no regressions**

```bash
local-stt stop && local-stt start
```

Say several German sentences. Check log for correct German output.

**Step 3: Commit**

```bash
cd /Users/uwefranke/Development/claude-stt
git add src/claude_stt/engines/mlx_engine.py
git commit -m "fix: add task=transcribe and temperature=0 to MLX engine"
```

---

## Task 5: Improve German initial_prompt

**Why:** Whisper treats `initial_prompt` as a previous-segment context. A keyword dump works for vocabulary, but a natural German sentence primes the decoder much more effectively for German output.

**This task is a config change only.**

**Step 1: Update initial_prompt in config.toml**

Replace the current keyword list with a German lead sentence followed by the keywords:

```toml
initial_prompt = "Gesprochener Text auf Deutsch über folgende Themen: Advisior, Cotedo, KiCo, Tradvisior, ExtraETF, Launchpad, Brixsta, Designreisen, Rebrickable, Topix, Datagroup, Proparc, Spareparts. Technologie: Server, Client, Tmux, Zed, Hetzner, Coolify, PostgreSQL, Redis, TypeScript, Node.js, React, Docker, GitHub Actions, Microservices, DSGVO, pnpm, Changesets, Hexagonal Architecture."
```

**Step 2: Restart daemon and test**

```bash
local-stt stop && local-stt start
```

Test with mixed-context phrases: "Kannst du im Tradvisior den IB-Import fixen?"

---

## Validation After All Tasks

Run through this checklist:

- [ ] Short tap (< 0.8s): log shows `Skipping: recording too short`, no sound
- [ ] Long silence recording: log shows `Skipping: audio too quiet`
- [ ] Normal German sentence: log shows correct German text
- [ ] Under CPU load (open many tabs, start a build): German output still correct
- [ ] Project names (Tradvisior, Cotedo, Brixsta): transcribed correctly

---

## Expected Outcome

| Scenario | Before | After |
|----------|--------|-------|
| Normal recording, low CPU | German, mostly correct | German, better accuracy |
| Recording under CPU load | English garbage | German, robust |
| Short accidental tap | Hallucination or empty | Silently ignored |
| Near-silence recording | Hallucination | Silently ignored |
| Debug "what was transcribed" | Impossible (logs blind) | Visible in daemon.log |
