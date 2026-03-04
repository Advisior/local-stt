# Transcript History + Mute-on-Record Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a transcript history window where users can click on misrecognized words to correct them (corrections saved to config.toml), plus an option to mute system audio during recording.

**Architecture:**
- Python daemon writes each transcription to `history.jsonl` (append-only, max 100 entries)
- Corrections stored in `config.toml` under `[corrections]` table as `wrong = "right"`
- `formatter.py` reads corrections from config (in addition to hardcoded `_CORRECTIONS`)
- New SwiftUI `HistoryView.swift` reads `history.jsonl`, shows words as clickable buttons
- Click word → correction popover → saves to config.toml via ConfigManager
- Mute: `osascript` before/after recording, guarded by `mute_on_record` config flag

**Tech Stack:** Python 3.11, SwiftUI/AppKit (macOS), TOML, JSONL

---

## Task 1: Python — Write history.jsonl after each transcription

**Files:**
- Modify: `src/claude_stt/daemon_service.py`

**Context:** After the `output_text(...)` call in `_transcribe_worker`, append a JSON line to `~/.claude/plugins/claude-stt/history.jsonl`. Keep max 100 entries (trim oldest when over limit).

**History entry format:**
```json
{"timestamp": "2026-02-26T11:16:20", "text": "Sorry, wenn es...", "duration_s": 3.6, "db": -30.9, "words": 14}
```

**Step 1: Add `_append_history` method to STTDaemon**

Add this method to the `STTDaemon` class:

```python
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
    # Read existing entries
    entries = []
    if history_path.exists():
        try:
            entries = [json.loads(l) for l in history_path.read_text().splitlines() if l.strip()]
        except Exception:
            entries = []
    # Append + trim to 100
    entries.append(entry)
    entries = entries[-100:]
    history_path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
```

**Step 2: Call `_append_history` in `_transcribe_worker`**

After `output_text(...)`, add:
```python
# duration stored when recording stopped, pass it via instance var
self._append_history(text, self._last_duration_s, db)
```

**Step 3: Store last recording duration**

In `_on_recording_stop`, after `elapsed = time.time() - self._record_start_time`, add:
```python
self._last_duration_s = elapsed
```

Also add `self._last_duration_s: float = 0.0` to `__init__`.

**Step 4: Verify file parses**
```bash
cd /Users/uwefranke/Development/claude-stt
python3 -m py_compile src/claude_stt/daemon_service.py && echo OK
```

**Step 5: Commit**
```bash
git add src/claude_stt/daemon_service.py
git commit -m "feat: write transcription history to history.jsonl"
```

---

## Task 2: Python — Load user corrections from config.toml in formatter.py

**Files:**
- Modify: `src/claude_stt/config.py`
- Modify: `src/claude_stt/formatter.py`

**Context:** `config.toml` will have a `[corrections]` section. Python reads it and applies corrections alongside the hardcoded `_CORRECTIONS` list.

**Step 1: Add `corrections` field to `Config` dataclass in `config.py`**

After `initial_prompt: str | None = None`, add:
```python
corrections: dict[str, str] = field(default_factory=dict)
```

Also add `from dataclasses import dataclass, field` (replace existing `from dataclasses import dataclass`).

**Step 2: Load `[corrections]` table in `Config.load()` in `config.py`**

After `tomli.load(f)` loads `data`, add:
```python
corrections = {str(k): str(v) for k, v in data.get("corrections", {}).items()}
```

Then add `corrections=corrections` to the `config = cls(...)` call.

**Step 3: Apply user corrections in `formatter.py`**

Change `fix_transcription_errors` signature and body:

```python
def fix_transcription_errors(text: str, user_corrections: dict[str, str] | None = None) -> str:
    """Fix common Whisper mis-transcriptions (hardcoded + user-defined)."""
    # Apply hardcoded corrections
    for pattern, replacement in _CORRECTIONS:
        text = pattern.sub(replacement, text)
    # Apply user corrections from config (case-sensitive whole-word)
    if user_corrections:
        for wrong, right in user_corrections.items():
            pattern = re.compile(r'\b' + re.escape(wrong) + r'\b')
            text = pattern.sub(right, text)
    return text
```

**Step 4: Pass corrections in `daemon_service.py`**

In `_transcribe_worker`, change:
```python
text = fix_transcription_errors(text)
```
to:
```python
text = fix_transcription_errors(text, self.config.corrections)
```

**Step 5: Verify both files parse**
```bash
python3 -m py_compile src/claude_stt/config.py && echo config OK
python3 -m py_compile src/claude_stt/formatter.py && echo formatter OK
python3 -m py_compile src/claude_stt/daemon_service.py && echo daemon OK
```

**Step 6: Commit**
```bash
git add src/claude_stt/config.py src/claude_stt/formatter.py src/claude_stt/daemon_service.py
git commit -m "feat: load user corrections from config.toml [corrections] table"
```

---

## Task 3: Python — Mute system audio during recording

**Files:**
- Modify: `src/claude_stt/config.py`
- Modify: `src/claude_stt/daemon_service.py`

**Context:** If `mute_on_record = true` in config, run `osascript` to mute system audio when recording starts and restore it when recording stops. Store original volume to restore correctly.

**Step 1: Add `mute_on_record` to `Config` dataclass in `config.py`**

After `sound_effects: bool = True`, add:
```python
mute_on_record: bool = False
```

Load in `Config.load()`:
```python
mute_on_record=stt_config.get("mute_on_record", cls.mute_on_record),
```

Save in `Config.save()`:
```python
"mute_on_record": self.mute_on_record,
```

**Step 2: Add mute helpers to `STTDaemon` in `daemon_service.py`**

Add `self._pre_record_volume: int | None = None` to `__init__`.

Add these two methods:

```python
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
```

**Step 3: Call mute/restore in `_on_recording_start` and `_on_recording_stop`**

In `_on_recording_start`, after `self._recording = True`, add:
```python
if self.config.mute_on_record:
    self._mute_system_audio()
```

In `_on_recording_stop`, after `self._recording = False`, add:
```python
if self.config.mute_on_record:
    self._restore_system_audio()
```

**Step 4: Verify**
```bash
python3 -m py_compile src/claude_stt/daemon_service.py && echo OK
python3 -m py_compile src/claude_stt/config.py && echo OK
```

**Step 5: Commit**
```bash
git add src/claude_stt/daemon_service.py src/claude_stt/config.py
git commit -m "feat: mute system audio during recording (mute_on_record config option)"
```

---

## Task 4: Swift — ConfigManager: add corrections, mute_on_record, save [corrections] section

**Files:**
- Modify: `menubar-app/Sources/ConfigManager.swift`

**Context:** ConfigManager needs to:
1. Load `[corrections]` table from config.toml into a `[String: String]` dict
2. Add `mute_on_record: Bool`
3. Save both back in `save()`
4. Expose `addCorrection(wrong:right:)` method

**Step 1: Add published properties**

In the `@Published` block, add:
```swift
@Published var corrections: [String: String] = [:]
@Published var muteOnRecord: Bool = false
```

**Step 2: Load in `load()` method**

Find the `load()` method. After reading the `[claude-stt]` section, add:
```swift
// Load [corrections] table
if let corrTable = dict["corrections"] as? [String: Any] {
    corrections = corrTable.compactMapValues { $0 as? String }
} else {
    corrections = [:]
}
```

Also load `muteOnRecord` from the `[claude-stt]` section:
```swift
muteOnRecord = sttSection["mute_on_record"] as? Bool ?? false
```

**Note:** ConfigManager uses a hand-rolled TOML parser. Check the existing `load()` method to see how it reads the `[claude-stt]` section and follow the same pattern for `[corrections]`.

**Step 3: Save in `save()` method**

After writing the `[claude-stt]` section, add:
```swift
lines.append("mute_on_record = \(muteOnRecord)")
```

And after all `[claude-stt]` lines, add the corrections section:
```swift
if !corrections.isEmpty {
    lines.append("")
    lines.append("[corrections]")
    for (wrong, right) in corrections.sorted(by: { $0.key < $1.key }) {
        lines.append("\(wrong) = \"\(escape(right))\"")
    }
}
```

**Step 4: Add `addCorrection` helper**

```swift
func addCorrection(wrong: String, right: String) {
    let trimmedWrong = wrong.trimmingCharacters(in: .whitespaces)
    let trimmedRight = right.trimmingCharacters(in: .whitespaces)
    guard !trimmedWrong.isEmpty, !trimmedRight.isEmpty, trimmedWrong != trimmedRight else { return }
    corrections[trimmedWrong] = trimmedRight
    save()
}
```

**Step 5: Build to verify (Swift compiler)**
```bash
cd /Users/uwefranke/Development/claude-stt/menubar-app
swift build 2>&1 | head -30
```

**Step 6: Commit**
```bash
cd /Users/uwefranke/Development/claude-stt
git add menubar-app/Sources/ConfigManager.swift
git commit -m "feat: add corrections dict and mute_on_record to ConfigManager"
```

---

## Task 5: Swift — HistoryView.swift (new file)

**Files:**
- Create: `menubar-app/Sources/HistoryView.swift`

**Context:** Shows transcript history from `history.jsonl`. Each entry is a card with the timestamp and words rendered as clickable buttons. Clicking a word opens an inline correction input. Saving writes the correction via `ConfigManager.addCorrection()`.

**Step 1: Create `HistoryView.swift`**

```swift
import SwiftUI

struct HistoryEntry: Identifiable {
    let id = UUID()
    let timestamp: String
    let text: String
    let durationS: Double
    let db: Double
}

struct HistoryView: View {
    @ObservedObject var config: ConfigManager
    var onDismiss: () -> Void

    @State private var entries: [HistoryEntry] = []
    @State private var selectedWord: String = ""
    @State private var correctionText: String = ""
    @State private var correctionEntryId: UUID? = nil
    @State private var correctionWordIndex: Int = -1

    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack {
                Text("Transcript History")
                    .font(.headline)
                Spacer()
                Button("Close") { onDismiss() }
                    .buttonStyle(.plain)
                    .foregroundColor(.secondary)
            }
            .padding()

            Divider()

            if entries.isEmpty {
                Spacer()
                Text("No transcriptions yet.")
                    .foregroundColor(.secondary)
                Spacer()
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 8) {
                        ForEach(entries) { entry in
                            EntryCard(
                                entry: entry,
                                corrections: config.corrections,
                                correctionEntryId: $correctionEntryId,
                                correctionWordIndex: $correctionWordIndex,
                                correctionText: $correctionText,
                                selectedWord: $selectedWord,
                                onSaveCorrection: { wrong, right in
                                    config.addCorrection(wrong: wrong, right: right)
                                    correctionEntryId = nil
                                    correctionWordIndex = -1
                                }
                            )
                        }
                    }
                    .padding()
                }
            }
        }
        .frame(width: 560, height: 480)
        .onAppear { loadHistory() }
    }

    private func loadHistory() {
        let historyURL = ConfigManager.configDir.appendingPathComponent("history.jsonl")
        guard let content = try? String(contentsOf: historyURL) else { return }
        let lines = content.split(separator: "\n", omittingEmptySubsequences: true)
        entries = lines.compactMap { line -> HistoryEntry? in
            guard let data = line.data(using: .utf8),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let text = json["text"] as? String,
                  let timestamp = json["timestamp"] as? String
            else { return nil }
            return HistoryEntry(
                timestamp: timestamp,
                text: text,
                durationS: json["duration_s"] as? Double ?? 0,
                db: json["db"] as? Double ?? 0
            )
        }.reversed()
    }
}

struct EntryCard: View {
    let entry: HistoryEntry
    let corrections: [String: String]
    @Binding var correctionEntryId: UUID?
    @Binding var correctionWordIndex: Int
    @Binding var correctionText: String
    @Binding var selectedWord: String
    var onSaveCorrection: (String, String) -> Void

    private var words: [String] {
        entry.text.split(separator: " ", omittingEmptySubsequences: true).map(String.init)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            // Timestamp + meta
            HStack(spacing: 8) {
                Text(entry.timestamp)
                    .font(.caption)
                    .foregroundColor(.secondary)
                Text(String(format: "%.1fs", entry.durationS))
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            // Words as clickable tokens
            FlowLayout(spacing: 4) {
                ForEach(Array(words.enumerated()), id: \.offset) { index, word in
                    let cleanWord = word.trimmingCharacters(in: .punctuationCharacters)
                    let isCorrected = corrections[cleanWord] != nil
                    let isSelected = correctionEntryId == entry.id && correctionWordIndex == index

                    Button(action: {
                        if isSelected {
                            correctionEntryId = nil
                            correctionWordIndex = -1
                        } else {
                            selectedWord = cleanWord
                            correctionText = corrections[cleanWord] ?? cleanWord
                            correctionEntryId = entry.id
                            correctionWordIndex = index
                        }
                    }) {
                        Text(word)
                            .padding(.horizontal, 5)
                            .padding(.vertical, 2)
                            .background(
                                isCorrected ? Color.orange.opacity(0.2) :
                                isSelected ? Color.accentColor.opacity(0.15) :
                                Color.secondary.opacity(0.08)
                            )
                            .foregroundColor(isCorrected ? .orange : .primary)
                            .cornerRadius(4)
                    }
                    .buttonStyle(.plain)
                }
            }

            // Inline correction input (shown when word is selected in this entry)
            if correctionEntryId == entry.id && correctionWordIndex >= 0 {
                HStack(spacing: 8) {
                    Text("\"\(selectedWord)\"")
                        .foregroundColor(.secondary)
                    Image(systemName: "arrow.right")
                        .foregroundColor(.secondary)
                    TextField("Correction", text: $correctionText)
                        .textFieldStyle(.roundedBorder)
                        .frame(width: 160)
                        .onSubmit {
                            onSaveCorrection(selectedWord, correctionText)
                        }
                    Button("Save") {
                        onSaveCorrection(selectedWord, correctionText)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.small)
                    Button("Cancel") {
                        correctionEntryId = nil
                        correctionWordIndex = -1
                    }
                    .buttonStyle(.plain)
                    .foregroundColor(.secondary)
                    .controlSize(.small)
                }
                .padding(.top, 4)
            }
        }
        .padding(10)
        .background(Color(NSColor.controlBackgroundColor))
        .cornerRadius(8)
    }
}

/// Simple flow layout for wrapping word buttons
struct FlowLayout: Layout {
    var spacing: CGFloat = 4

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > maxWidth && x > 0 {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
        return CGSize(width: maxWidth, height: y + rowHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX
        var y = bounds.minY
        var rowHeight: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > bounds.maxX && x > bounds.minX {
                x = bounds.minX
                y += rowHeight + spacing
                rowHeight = 0
            }
            subview.place(at: CGPoint(x: x, y: y), proposal: .unspecified)
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}
```

**Step 2: Build to verify**
```bash
cd /Users/uwefranke/Development/claude-stt/menubar-app
swift build 2>&1 | head -30
```

**Step 3: Fix any compiler errors** (SwiftUI Layout API requires macOS 13+; if build target is lower, implement FlowLayout with VStack/HStack fallback instead)

**Step 4: Commit**
```bash
cd /Users/uwefranke/Development/claude-stt
git add menubar-app/Sources/HistoryView.swift
git commit -m "feat: add HistoryView with clickable word corrections"
```

---

## Task 6: Swift — Wire History window into MenuBarController + MenuPopoverView

**Files:**
- Modify: `menubar-app/Sources/MenuBarController.swift`
- Modify: `menubar-app/Sources/MenuPopoverView.swift`

**Context:** Same pattern as `onOpenSettings()` / Settings menu item.

**Step 1: Add `historyWindow` var and `onOpenHistory()` to `MenuBarController.swift`**

Add instance var after `settingsWindow`:
```swift
private var historyWindow: NSWindow?
```

Add method (copy pattern from `onOpenSettings`, adapt for HistoryView, size 560×520):
```swift
private func onOpenHistory() {
    if let window = historyWindow, window.isVisible {
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        return
    }
    historyWindow?.close()
    historyWindow = nil

    let historyView = HistoryView(
        config: config,
        onDismiss: { [weak self] in
            self?.historyWindow?.close()
        }
    )
    let hostingView = NSHostingView(rootView: historyView)
    let window = NSWindow(
        contentRect: NSRect(x: 0, y: 0, width: 560, height: 520),
        styleMask: [.titled, .closable],
        backing: .buffered,
        defer: false
    )
    window.title = "Transcript History"
    window.contentView = hostingView
    window.isReleasedWhenClosed = false
    // Center on active monitor (same pattern as settings)
    let mouseLocation = NSEvent.mouseLocation
    let activeScreen = NSScreen.screens.first { NSMouseInRect(mouseLocation, $0.frame, false) } ?? NSScreen.main
    if let screen = activeScreen {
        let sf = screen.visibleFrame
        window.setFrameOrigin(NSPoint(x: sf.midX - 280, y: sf.midY - 260))
    } else {
        window.center()
    }
    window.makeKeyAndOrderFront(nil)
    NSApp.activate(ignoringOtherApps: true)
    historyWindow = window
}
```

Wire into the popover callback block (same place as `onSettings`):
```swift
onHistory: { [weak self] in
    self?.closePopover()
    self?.onOpenHistory()
},
```

**Step 2: Add `onHistory` callback + menu item to `MenuPopoverView.swift`**

Add property after `onOpenLog`:
```swift
var onHistory: () -> Void
```

Add menu item (place it between the log item and settings item):
```swift
PopoverMenuItem(
    icon: "clock.arrow.circlepath",
    label: "History"
) {
    onHistory()
}
```

**Step 3: Build to verify**
```bash
cd /Users/uwefranke/Development/claude-stt/menubar-app
swift build 2>&1 | head -30
```

**Step 4: Commit**
```bash
cd /Users/uwefranke/Development/claude-stt
git add menubar-app/Sources/MenuBarController.swift menubar-app/Sources/MenuPopoverView.swift
git commit -m "feat: add History menu item and window"
```

---

## Task 7: Swift — Add mute_on_record toggle to SettingsView

**Files:**
- Modify: `menubar-app/Sources/SettingsView.swift`

**Context:** Simple toggle, similar to the `sound_effects` toggle already in SettingsView.

**Step 1: Find the sound_effects toggle in SettingsView.swift and add mute toggle below it**

```swift
Toggle("Mute system audio while recording", isOn: $config.muteOnRecord)
    .onChange(of: config.muteOnRecord) { _ in config.save() }
```

**Step 2: Build and verify**
```bash
cd /Users/uwefranke/Development/claude-stt/menubar-app
swift build 2>&1 | head -30
```

**Step 3: Commit**
```bash
cd /Users/uwefranke/Development/claude-stt
git add menubar-app/Sources/SettingsView.swift
git commit -m "feat: add mute_on_record toggle to Settings"
```

---

## Validation Checklist

- [ ] Speak something → `history.jsonl` appears in `~/.claude/plugins/claude-stt/`
- [ ] History window opens via menu
- [ ] Words are clickable, correction input appears inline
- [ ] Save correction → `[corrections]` section appears in `config.toml`
- [ ] Restart daemon → correction is applied to next matching transcription
- [ ] Mute toggle in Settings works — system audio mutes during recording, restores after
- [ ] Short tap still ignored (min_recording_seconds guard still active)
