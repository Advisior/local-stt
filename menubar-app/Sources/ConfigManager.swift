import Foundation
import Combine

class ConfigManager: ObservableObject {
    // Editable settings
    @Published var hotkey: String = "ctrl+shift+space"
    @Published var mode: String = "toggle"
    @Published var language: String = ""
    @Published var initialPrompt: String = ""
    @Published var soundEffects: Bool = true
    @Published var autoStartDaemon: Bool = true

    // Read-only display
    @Published var engine: String = "moonshine"
    @Published var whisperModel: String = "medium"
    @Published var moonshineModel: String = "moonshine/base"

    static var configDir: URL {
        if let override = ProcessInfo.processInfo.environment["CLAUDE_STT_CONFIG_DIR"] {
            return URL(fileURLWithPath: override)
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".claude/plugins/claude-stt")
    }

    private var configURL: URL {
        Self.configDir.appendingPathComponent("config.toml")
    }

    /// Human-readable hotkey label for display in menus (e.g. "⌘R", "F1", "⌃⇧Space")
    var hotkeyLabel: String {
        let parts = hotkey.split(separator: "+").map(String.init)
        var symbols: [String] = []

        for part in parts {
            let lower = part.lowercased().trimmingCharacters(in: .whitespaces)
            switch lower {
            // Side-specific keys used as standalone hotkeys (e.g. "cmd_r" = right ⌘)
            case "cmd_r": symbols.append("\u{2318}R")
            case "cmd_l": symbols.append("\u{2318}L")
            case "ctrl_r": symbols.append("\u{2303}R")
            case "ctrl_l": symbols.append("\u{2303}L")
            case "alt_r": symbols.append("\u{2325}R")
            case "alt_l": symbols.append("\u{2325}L")
            case "shift_r": symbols.append("\u{21E7}R")
            case "shift_l": symbols.append("\u{21E7}L")
            // Generic modifiers (used in combos like ctrl+shift+space)
            case "ctrl": symbols.append("\u{2303}")
            case "alt", "option": symbols.append("\u{2325}")
            case "shift": symbols.append("\u{21E7}")
            case "cmd", "command": symbols.append("\u{2318}")
            case "space": symbols.append("Space")
            default:
                // F-keys, single letters, etc.
                if lower.hasPrefix("f") && lower.count <= 3 && Int(lower.dropFirst()) != nil {
                    symbols.append(part.uppercased())
                } else {
                    symbols.append(part.capitalized)
                }
            }
        }

        return symbols.joined()
    }

    var engineLabel: String {
        switch engine {
        case "mlx": return "mlx (\(whisperModel))"
        case "whisper": return "whisper (\(whisperModel))"
        default: return "moonshine (\(moonshineModel))"
        }
    }

    init() {
        load()
    }

    // MARK: - TOML Read

    func load() {
        guard let content = try? String(contentsOf: configURL, encoding: .utf8)
        else { return }

        for line in content.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard !trimmed.hasPrefix("["),
                  !trimmed.hasPrefix("#"),
                  !trimmed.isEmpty
            else { continue }

            let parts = trimmed.split(separator: "=", maxSplits: 1)
            guard parts.count == 2 else { continue }

            let key = parts[0].trimmingCharacters(in: .whitespaces)
            let raw = parts[1].trimmingCharacters(in: .whitespaces)
            let value = unquote(raw)

            switch key {
            case "hotkey": hotkey = value
            case "mode": mode = value
            case "engine": engine = value
            case "whisper_model": whisperModel = value
            case "moonshine_model": moonshineModel = value
            case "language": language = value
            case "initial_prompt": initialPrompt = value
            case "sound_effects": soundEffects = (value == "true")
            case "auto_start_daemon": autoStartDaemon = (value == "true")
            default: break
            }
        }
    }

    // MARK: - Validation

    private static let validEngines = ["mlx", "whisper", "moonshine"]
    private static let validModes = ["push-to-talk", "toggle"]
    private static let maxInitialPromptLength = 1000

    /// Validates and sanitizes all config fields before saving.
    /// Returns true if all fields are valid, false if any were corrected.
    @discardableResult
    func validate() -> Bool {
        var wasValid = true

        // Hotkey: only alphanumeric, +, _, and common modifier names
        let hotkeyPattern = #"^[a-zA-Z0-9+_\-\s]+$"#
        if hotkey.range(of: hotkeyPattern, options: .regularExpression) == nil
            || hotkey.isEmpty {
            NSLog("Claude STT: Invalid hotkey '%@', resetting to default", hotkey)
            hotkey = "ctrl+shift+space"
            wasValid = false
        }

        // Engine: must be one of the known engines
        if !Self.validEngines.contains(engine) {
            NSLog("Claude STT: Invalid engine '%@', resetting to moonshine", engine)
            engine = "moonshine"
            wasValid = false
        }

        // Mode: must be one of the known modes
        if !Self.validModes.contains(mode) {
            NSLog("Claude STT: Invalid mode '%@', resetting to toggle", mode)
            mode = "toggle"
            wasValid = false
        }

        // Language: empty or 2-letter ISO code
        if !language.isEmpty {
            let langPattern = #"^[a-z]{2}$"#
            if language.range(of: langPattern, options: .regularExpression) == nil {
                NSLog("Claude STT: Invalid language '%@', clearing", language)
                language = ""
                wasValid = false
            }
        }

        // Initial prompt: clamp to max length
        if initialPrompt.count > Self.maxInitialPromptLength {
            NSLog("Claude STT: initialPrompt too long (%d chars), truncating to %d",
                  initialPrompt.count, Self.maxInitialPromptLength)
            initialPrompt = String(initialPrompt.prefix(Self.maxInitialPromptLength))
            wasValid = false
        }

        return wasValid
    }

    // MARK: - TOML Write

    func save() {
        validate()
        var lines = ["[claude-stt]"]
        lines.append("hotkey = \"\(escape(hotkey))\"")
        lines.append("mode = \"\(mode)\"")
        lines.append("engine = \"\(engine)\"")
        lines.append("moonshine_model = \"\(escape(moonshineModel))\"")
        lines.append("whisper_model = \"\(escape(whisperModel))\"")
        lines.append("sample_rate = 16000")
        lines.append("max_recording_seconds = 300")
        lines.append("output_mode = \"auto\"")
        lines.append("sound_effects = \(soundEffects)")
        lines.append("auto_start_daemon = \(autoStartDaemon)")

        if !language.isEmpty {
            lines.append("language = \"\(escape(language))\"")
        }
        if !initialPrompt.isEmpty {
            lines.append("initial_prompt = \"\(escape(initialPrompt))\"")
        }

        let content = lines.joined(separator: "\n") + "\n"

        try? FileManager.default.createDirectory(
            at: Self.configDir, withIntermediateDirectories: true
        )
        try? content.write(to: configURL, atomically: true, encoding: .utf8)
    }

    // MARK: - Helpers

    private func unquote(_ s: String) -> String {
        var v = s
        if v.hasPrefix("\"") && v.hasSuffix("\"") && v.count >= 2 {
            v = String(v.dropFirst().dropLast())
            v = v.replacingOccurrences(of: "\\\"", with: "\"")
            v = v.replacingOccurrences(of: "\\\\", with: "\\")
        }
        return v
    }

    private func escape(_ s: String) -> String {
        s.replacingOccurrences(of: "\\", with: "\\\\")
         .replacingOccurrences(of: "\"", with: "\\\"")
    }
}
