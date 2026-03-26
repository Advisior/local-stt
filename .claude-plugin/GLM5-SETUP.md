# GLM-5 Backend Setup fuer Claude Code

Wenn die Anthropic-Subscription laeuft, kannst du GLM-5 von Z.AI als kostenlosen Ersatz nutzen.

## 1. Z.AI Account erstellen

Besuche [z.ai](https://z.ai) und erstelle kostenlosen Account.

## 2. API Key generieren

In Z.AI Open Platform → API Keys → New API Key → Name `local-stt-glm` → Create

```
local-stt
```

WICHTIG: Der Key beginnt mit `sk-`, also im `.zshrc` Alias `__ZAI_API_KEY__` statt `ANTHROPIC_AUTH_TOKEN`.

## 3. ~/.claude/settings-glm.json einrichten

Die Datei `settings-glm.json` ist das Claude Config File, aber Z.AI nutzt dieselbe Struktur. Einfach:

```json
{
  "env": {
    "ANTHROPIC_AUTH_TOKEN": "dein-zai-api-key-hier"
  },
  "permissions": { ... }
}
```

## 4. Shell Alias nutzen

Nach `source ~/.zshrc` stehen die Aliases bereit:

```bash
claude-glm              # Startet mit GLM-5
claude-opus             # Zurueck zu Anthropic/Opus
```

## 5. Umschalten

```bash
# Nach Key-Eintrag
source ~/.zshrc

# Neuen Terminal oeffnen (wichtig!)
```

## Model-Auswahl

Z.AI bietet mehrere Modelle (GLM-5, GLM-4, GLM-3-Spark). Standard ist GLM-5.

```bash
# Model aendern (optional)
claude --set-default-model <model-name>
```

## Weiter

- Dokumentation: [docs.z.ai/guides/llm/glm-5](https://docs.z.ai/guides/llm/glm-5)
- Forum: [Z.ai Community](https://z.ai/learn)

**Hinweis:** GLM-5 ist Open-Source (MIT), aber die Modelle selbst sind proprietare (Weights nicht oeffentlich).
