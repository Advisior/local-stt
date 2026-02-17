# Local-STT - Lokale Spracheingabe fuer macOS

Kostenlose, lokale, private Speech-to-Text fuer deinen Mac. Keine Cloud, keine API-Kosten, keine Daten verlassen dein Geraet.

**Was du bekommst:** Rechte CMD-Taste halten, Deutsch sprechen, loslassen - Text erscheint an deinem Cursor. Funktioniert in jeder App.

## Voraussetzungen

- macOS mit Apple Silicon (M1/M2/M3/M4/M5)
- Python 3.11-3.13 (nicht 3.14+)
- ~1.5 GB Speicher fuer das Whisper Medium Model (wird einmalig heruntergeladen)
- Mikrofon-Zugriff

## Download & Installation

### Option A: Fertige App herunterladen (empfohlen)

1. `Local-STT-v*.zip` von der [Releases-Seite](https://github.com/Advisior/local-stt/releases) herunterladen
2. Entpacken und **Local-STT.app** nach `/Applications` ziehen
3. Aus dem Programme-Ordner starten

**Hinweis:** Beim ersten Start meldet macOS moeglicherweise "App von einem nicht verifizierten Entwickler". Rechtsklick auf die App > Oeffnen > Oeffnen.

### Option B: Selbst bauen

```bash
# 1. Klonen
git clone https://github.com/Advisior/local-stt.git
cd local-stt

# 2. venv mit kompatiblem Python erstellen
python3.12 -m venv .venv   # oder python3.11, python3.13
source .venv/bin/activate

# 3. Mit MLX-Support installieren
pip install -e .
pip install mlx-whisper

# 4. Menu-Bar-App bauen und installieren
bash scripts/build-app.sh
bash scripts/install-app.sh
```

## Erste Schritte

1. **Local-STT starten** aus `/Applications`
2. **Berechtigungen erteilen** (siehe naechster Abschnitt)
3. **Einstellungen oeffnen** (Menu-Bar-Icon klicken > Settings)
4. **Sprache, Hotkey und Vokabular** nach Wunsch konfigurieren
5. **Hotkey halten** (Standard: rechte CMD), sprechen, loslassen

## Erforderliche macOS-Berechtigungen

Local-STT braucht drei Berechtigungen. Beim ersten Start erscheinen drei System-Dialoge nacheinander:

1. **Mikrofon** - "Local-STT moechte auf das Mikrofon zugreifen." Klicke **OK**.
2. **Bedienungshilfen** - "Local-STT moechte diesen Computer steuern." Klicke **Systemeinstellungen oeffnen**, dann den Schalter fuer Local-STT aktivieren.
3. **System Events / Automation** - "Local-STT moechte auf System Events zugreifen." Klicke **OK**.

| Berechtigung | Zweck | Wo erteilen |
|-------------|-------|-------------|
| **Mikrofon** | Audioaufnahme | Systemeinstellungen > Datenschutz & Sicherheit > Mikrofon |
| **Bedienungshilfen** | Hotkey-Erkennung (pynput) | Systemeinstellungen > Datenschutz & Sicherheit > Bedienungshilfen |
| **Eingabeueberwachung** | Tastaturueberwachung | Systemeinstellungen > Datenschutz & Sicherheit > Eingabeueberwachung |

**Nach Erteilung der Bedienungshilfen-Berechtigung den Daemon neu starten** (Stop + Start in der Menu Bar).

Das STT-Model (~1.5 GB) wird einmalig von HuggingFace heruntergeladen. Danach laeuft alles 100% offline.

## Vokabular anpassen

Das Vokabular (unter Settings > Transcription > Vocabulary) teilt Whisper mit, welche Fachbegriffe du nutzt. Das verbessert die Erkennung technischer Woerter drastisch.

### Beispiele nach Fachbereich

**Web Development:**
```
TypeScript, React, Next.js, Tailwind CSS, Prisma, tRPC, Zustand, Vite, ESLint, Prettier, Vercel, Supabase, PostgreSQL, Redis, Docker, Kubernetes, GitHub Actions, CI/CD Pipeline, REST API, GraphQL, WebSocket
```

**Data Science / ML:**
```
Python, Jupyter, pandas, NumPy, scikit-learn, TensorFlow, PyTorch, Matplotlib, Hugging Face, Transformers, CUDA, MLflow, Feature Engineering, Hyperparameter Tuning, Random Forest, Gradient Boosting, Neural Network
```

**DevOps / Infrastruktur:**
```
Terraform, Ansible, Kubernetes, Helm, ArgoCD, Prometheus, Grafana, Docker Compose, nginx, Caddy, Let's Encrypt, Hetzner, AWS, CloudFlare, GitHub Actions, GitLab CI, SonarQube, Vault, Consul
```

**Finanzen / Banking:**
```
MiFID, DSGVO, KYC, AML, PSD2, SWIFT, SEPA, BaFin, Bloomberg, Reuters, Portfolio, Derivate, Hedging, Compliance, Risikomanagement, Rendite, Volatilitaet
```

### Tipps fuer das Vokabular

- Unter ~500 Zeichen bleiben (Whisper kuerzt bei ~224 Tokens)
- Nur Eigennamen und Fachbegriffe auflisten, die Whisper sonst falsch schreiben wuerde
- Kommagetrennte Liste ist am Token-effizientesten
- Keine alltaeglichen Woerter noetig - nur spezialisiertes Vokabular

## Sprache

In Settings > Transcription > Language aenderbar:

| Sprache | Code |
|---------|------|
| Deutsch | `de` |
| Englisch | `en` |
| Franzoesisch | `fr` |
| Spanisch | `es` |
| Auto-Erkennung | Language auf "Auto-detect" stellen |

## Hotkey-Optionen

In Settings > General > Hotkey konfigurierbar (Klick auf das Feld, dann Taste druecken):

| Setup | Hotkey | Modus | Nutzung |
|-------|--------|-------|---------|
| **Rechte CMD (empfohlen)** | `cmd_r` | Push-to-Talk | Halten zum Sprechen, loslassen zum Transkribieren |
| Rechte CMD Toggle | `cmd_r` | Toggle | Druecken zum Starten, nochmal druecken zum Stoppen |
| Tastenkombination | `ctrl+shift+d` | Toggle | Kombination druecken zum Starten/Stoppen |
| Linke Alt | `alt_l` | Push-to-Talk | Linke Alt-Taste halten zum Sprechen |

**Seitenspezifische Tasten:** `cmd_r`, `cmd_l`, `ctrl_r`, `ctrl_l`, `shift_r`, `shift_l`, `alt_r`, `alt_l`

## Model-Groessen

In Settings > General > Model aenderbar:

| Model | Groesse | Speed (M1) | Qualitaet | Empfohlen fuer |
|-------|---------|------------|-----------|----------------|
| `tiny` | ~75 MB | ~0.5s | Niedrig | Schnelle Tests |
| `base` | ~150 MB | ~0.8s | OK | Nur Englisch, Speed-Prioritaet |
| `small` | ~500 MB | ~1.5s | Gut | Mehrsprachig, ausgewogen |
| **`medium`** | ~1.5 GB | ~2-3s | **Sehr gut** | **Empfohlen fuer Deutsch** |
| `large-v3` | ~3 GB | ~5-8s | Beste | Maximale Genauigkeit |

MLX nutzt automatisch 4-Bit-quantisierte Modelle fuer schnellere Inferenz.

## Deinstallation

```bash
bash scripts/uninstall-app.sh
```

Entfernt die App, stoppt den Daemon und bereinigt alle macOS-Berechtigungen. Konfiguration und Model-Cache bleiben erhalten - das Skript zeigt optionale Aufraeum-Befehle.

## Fehlerbehebung

| Problem | Loesung |
|---------|---------|
| Kein Ton bei Tastendruck | Systemeinstellungen > Datenschutz & Sicherheit > Mikrofon > Terminal-App pruefen |
| "No speech detected" (-93 dB) | Mikrofon-Eingangspegel pruefen: Systemeinstellungen > Ton > Eingabe |
| Falsche Sprache erkannt | Language in Settings > Transcription aendern |
| Langsame Transkription | Auf `small` Model wechseln oder andere GPU-Tasks beenden |
| Hotkey reagiert nicht | Wispr Flow oder andere STT-Tools beenden, die denselben Key nutzen |
| Python-Versionsfehler | Python 3.11-3.13 nutzen: `python3.12 -m venv .venv` |
| "pynput unavailable" | Bedienungshilfen-Zugriff erteilen |

## Logs

```bash
tail -f /tmp/claude-stt.log
```

Achte auf:
- `Audio input: Fifine Microphone` - richtiges Mikro erkannt
- `Transcribing audio (... samples, -20.5 dB)` - guter Signalpegel (-30 bis -10 dB ideal)
- `No speech detected` mit -90+ dB - Mikro stumm oder falsches Geraet
