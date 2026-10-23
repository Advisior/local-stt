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
    @Published var corrections: [String: String] = [:]
    @Published var muteOnRecord: Bool = false
    @Published var outputMode: String = "auto"
    @Published var undoHotkey: String = ""
    // Not editable here; kept as written so save() round-trips them.
    var undoWindowSeconds: String = "60.0"
    var undoMaxChars: String = "400"

    // Read-only display
    // Defaults for fresh installs; must match config.py. MLX Whisper needs Apple Silicon.
    #if arch(arm64)
    @Published var engine: String = "mlx"
    @Published var whisperModel: String = "large-v3-turbo"
    #else
    @Published var engine: String = "moonshine"
    @Published var whisperModel: String = "medium"
    #endif
    @Published var moonshineModel: String = "moonshine/base"
    @Published var parakeetModel: String = "tdt-0.6b-v3"

    static var configDir: URL {
        if let override = ProcessInfo.processInfo.environment["LOCAL_STT_CONFIG_DIR"]
            ?? ProcessInfo.processInfo.environment["CLAUDE_STT_CONFIG_DIR"] {
            return URL(fileURLWithPath: override)
        }
        let fm = FileManager.default
        let home = fm.homeDirectoryForCurrentUser
        let newDir = home.appendingPathComponent(".config/local-stt")
        let legacyDir = home.appendingPathComponent(".claude/plugins/claude-stt")
        // Migrate transparently: use legacy dir if it exists and new dir doesn't
        if !fm.fileExists(atPath: newDir.path) && fm.fileExists(atPath: legacyDir.path) {
            return legacyDir
        }
        return newDir
    }

    /// Directory this instance reads and writes; tests pass a temp dir.
    let configDirectory: URL

    private var configURL: URL {
        configDirectory.appendingPathComponent("config.toml")
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
        case "parakeet": return "parakeet (\(parakeetModel))"
        default: return "moonshine (\(moonshineModel))"
        }
    }

    /// Header subtitle in the status menu, "MLX Whisper · Large v3 Turbo".
    var serviceSummary: String {
        let model: String
        switch engine {
        case "parakeet": model = parakeetModel
        case "moonshine": model = moonshineModel
        default: model = whisperModel
        }
        let name = Self.modelDisplayName(model)
        let engineName = Self.engineDisplayName(engine)
        return name.isEmpty ? engineName : "\(engineName) \u{00B7} \(name)"
    }

    static func engineDisplayName(_ engine: String) -> String {
        switch engine {
        case "mlx": return "MLX Whisper"
        case "whisper": return "Whisper"
        case "parakeet": return "Parakeet"
        case "moonshine": return "Moonshine"
        default: return engine
        }
    }

    /// "mlx-community/whisper-large-v3-mlx" to "Large v3", "tdt-0.6b-v3" to "TDT 0.6B v3".
    static func modelDisplayName(_ model: String) -> String {
        var id = model.split(separator: "/").last.map(String.init) ?? model
        if id.hasSuffix("-mlx") { id = String(id.dropLast(4)) }
        if id.hasPrefix("whisper-") { id = String(id.dropFirst(8)) }
        return id.split(separator: "-").map { word -> String in
            let w = String(word)
            if w == "tdt" { return "TDT" }
            if w.range(of: #"^[0-9.]+b$"#, options: .regularExpression) != nil { return w.uppercased() }
            if w.allSatisfy(\.isLetter) { return w.prefix(1).uppercased() + w.dropFirst() }
            return w
        }.joined(separator: " ")
    }

    init(loadFromDisk: Bool = true, configDirectory: URL = ConfigManager.configDir) {
        self.configDirectory = configDirectory
        if loadFromDisk { load() }
    }

    // MARK: - TOML Read

    func load() {
        guard let content = try? String(contentsOf: configURL, encoding: .utf8)
        else { return }

        var currentSection = ""
        var loadedCorrections: [String: String] = [:]

        for line in content.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard !trimmed.hasPrefix("#"), !trimmed.isEmpty else { continue }

            if trimmed.hasPrefix("[") && trimmed.hasSuffix("]") {
                currentSection = String(trimmed.dropFirst().dropLast())
                continue
            }

            let parts = trimmed.split(separator: "=", maxSplits: 1)
            guard parts.count == 2 else { continue }

            let key = parts[0].trimmingCharacters(in: .whitespaces)
            let raw = parts[1].trimmingCharacters(in: .whitespaces)
            let value = unquote(raw)

            if currentSection == "corrections" {
                loadedCorrections[unquote(key)] = value
                continue
            }

            switch key {
            case "hotkey": hotkey = value
            case "mode": mode = value
            case "engine": engine = value
            case "whisper_model": whisperModel = value
            case "moonshine_model": moonshineModel = value
            case "parakeet_model": parakeetModel = value
            case "language": language = value
            case "initial_prompt": initialPrompt = value
            case "sound_effects": soundEffects = (value == "true")
            case "auto_start_daemon": autoStartDaemon = (value == "true")
            case "mute_on_record": muteOnRecord = (value == "true")
            case "output_mode": outputMode = value
            case "undo_hotkey": undoHotkey = value
            case "undo_window_seconds": undoWindowSeconds = value
            case "undo_max_chars": undoMaxChars = value
            default: break
            }
        }

        corrections = loadedCorrections
    }

    // MARK: - Validation

    private static let validEngines = ["mlx", "whisper", "moonshine", "parakeet"]
    private static let validModes = ["push-to-talk", "toggle"]
    private static let maxInitialPromptLength = 1000
    /// TOML 1.0 decimal integer or float without sign "-", inf or nan.
    static let tomlNumberPattern = #"^\+?(0|[1-9](_?[0-9])*)(\.[0-9](_?[0-9])*)?([eE][+-]?[0-9](_?[0-9])*)?$"#

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

        // Undo hotkey: optional, same characters as the record hotkey
        if !undoHotkey.isEmpty
            && undoHotkey.range(of: hotkeyPattern, options: .regularExpression) == nil {
            NSLog("Claude STT: Invalid undo hotkey '%@', clearing", undoHotkey)
            undoHotkey = ""
            wasValid = false
        }
        // Written back unquoted and unchanged, so any non-negative TOML
        // decimal number passes (underscores, exponent); the daemon converts.
        if undoWindowSeconds.range(of: Self.tomlNumberPattern, options: .regularExpression) == nil {
            undoWindowSeconds = "60.0"
            wasValid = false
        }
        if undoMaxChars.range(of: Self.tomlNumberPattern, options: .regularExpression) == nil {
            undoMaxChars = "400"
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

    /// Managed `[claude-stt]` keys in write order with their TOML value;
    /// nil removes the key line. `sample_rate` and `max_recording_seconds`
    /// are not managed, so user values for them survive a save.
    private var managedValues: [(key: String, value: String?)] {
        [
            ("hotkey", "\"\(escape(hotkey))\""),
            ("mode", "\"\(mode)\""),
            ("engine", "\"\(engine)\""),
            ("moonshine_model", "\"\(escape(moonshineModel))\""),
            ("whisper_model", "\"\(escape(whisperModel))\""),
            ("parakeet_model", "\"\(escape(parakeetModel))\""),
            ("output_mode", "\"\(escape(outputMode))\""),
            ("sound_effects", "\(soundEffects)"),
            ("auto_start_daemon", "\(autoStartDaemon)"),
            ("mute_on_record", "\(muteOnRecord)"),
            ("undo_hotkey", "\"\(escape(undoHotkey))\""),
            ("undo_window_seconds", undoWindowSeconds),
            ("undo_max_chars", undoMaxChars),
            ("language", language.isEmpty ? nil : "\"\(escape(language))\""),
            ("initial_prompt", initialPrompt.isEmpty ? nil : "\"\(escape(initialPrompt))\""),
        ]
    }

    private var correctionLines: [String] {
        corrections.sorted(by: { $0.key < $1.key }).map { wrong, right in
            "\"\(escape(wrong))\" = \"\(escape(right))\""
        }
    }

    /// Updates the managed keys and `[corrections]` in place and keeps every
    /// other line of `config.toml` (unknown keys, comments, other sections).
    func save() {
        validate()
        let fm = FileManager.default
        let existing: String?
        if fm.fileExists(atPath: configURL.path) {
            // Never replace a file we could not read; that would drop its keys.
            guard let text = try? String(contentsOf: configURL, encoding: .utf8) else {
                NSLog("Claude STT: config.toml unreadable, not saving")
                return
            }
            existing = text
        } else {
            existing = nil
        }

        let content = Self.mergedConfig(
            existing: existing, managed: managedValues, corrections: correctionLines
        )

        try? fm.createDirectory(at: configDirectory, withIntermediateDirectories: true)
        try? content.write(to: configURL, atomically: true, encoding: .utf8)
    }

    /// Line-based merge, no TOML library: the app writes only flat string,
    /// number and bool keys. Lines inside multi-line strings are left as is.
    static func mergedConfig(
        existing: String?,
        managed: [(key: String, value: String?)],
        corrections: [String]
    ) -> String {
        let managedLines = managed.compactMap { entry in
            entry.value.map { "\(entry.key) = \($0)" }
        }
        guard let existing, !existing.isEmpty else {
            var lines = ["[claude-stt]"] + managedLines
            if !corrections.isEmpty {
                lines += ["", "[corrections]"] + corrections
            }
            return lines.joined(separator: "\n") + "\n"
        }

        let values = Dictionary(managed.map { ($0.key, $0.value) }, uniquingKeysWith: { first, _ in first })
        var written = Set<String>()
        var output: [String] = []
        var section: String?          // nil = root table, before any header
        var sectionStart = 0          // index in `output` right after the header
        var sawMainSection = false
        var sawCorrections = false
        var multilineDelimiter: String?
        var dropContinuation = false  // drop the open multi-line value's lines

        // Called when a section ends: append managed keys still missing from
        // [claude-stt], or the new corrections, after its last content line.
        func closeSection() {
            var insertAt = output.count
            while insertAt > sectionStart,
                  output[insertAt - 1].trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                insertAt -= 1
            }
            if section == "claude-stt" {
                let missing = managed.compactMap { entry -> String? in
                    guard !written.contains(entry.key), let value = entry.value else { return nil }
                    return "\(entry.key) = \(value)"
                }
                output.insert(contentsOf: missing, at: insertAt)
            } else if section == "corrections" {
                output.insert(contentsOf: corrections, at: insertAt)
            }
        }

        // Keep the file's line ending; a CRLF file stays CRLF.
        let newline = existing.contains("\r\n") ? "\r\n" : "\n"
        var lines = existing.components(separatedBy: newline)
        if existing.hasSuffix(newline) { lines.removeLast() }
        for line in lines {
            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)

            if let delimiter = multilineDelimiter {
                if !dropContinuation { output.append(line) }
                if trimmed.components(separatedBy: delimiter).count % 2 == 0 { multilineDelimiter = nil }
                continue
            }

            if let header = sectionName(trimmed) {
                closeSection()
                section = header
                output.append(line)
                sectionStart = output.count
                if header == "claude-stt" { sawMainSection = true }
                if header == "corrections" { sawCorrections = true }
                continue
            }

            if section == "corrections" {
                // Entries and comments are replaced; blank lines stay so the
                // spacing before the next section does not change.
                if trimmed.isEmpty { output.append(line) }
                multilineDelimiter = openedMultiline(trimmed)
                dropContinuation = true
                continue
            }

            if section == "claude-stt", !trimmed.hasPrefix("#"),
               let eq = trimmed.firstIndex(of: "=") {
                let key = unquoteKey(trimmed[..<eq].trimmingCharacters(in: .whitespaces))
                if let value = values[key] {
                    written.insert(key)
                    if let value { output.append("\(key) = \(value)") }
                    // The old value may span lines; they go with it.
                    multilineDelimiter = openedMultiline(trimmed)
                    dropContinuation = true
                    continue
                }
            }
            output.append(line)
            multilineDelimiter = openedMultiline(trimmed)
            dropContinuation = false
        }
        closeSection()

        if !sawMainSection {
            appendSection(&output, header: "[claude-stt]", body: managedLines)
        }
        if !sawCorrections && !corrections.isEmpty {
            appendSection(&output, header: "[corrections]", body: corrections)
        }
        return output.joined(separator: newline) + newline
    }

    /// Table name of a header line such as `[claude-stt]  # note`, else nil.
    /// An array-of-tables header `[[x]]` returns "[[x]]", so it ends the
    /// current section but never matches a section the app manages.
    private static func sectionName(_ trimmed: String) -> String? {
        let isArray = trimmed.hasPrefix("[[")
        let open = isArray ? "[[" : "["
        let closing = isArray ? "]]" : "]"
        guard trimmed.hasPrefix(open),
              let close = trimmed.range(of: closing) else { return nil }
        let rest = trimmed[close.upperBound...].trimmingCharacters(in: .whitespaces)
        guard rest.isEmpty || rest.hasPrefix("#") else { return nil }
        let name = unquoteKey(trimmed[trimmed.index(trimmed.startIndex, offsetBy: open.count)..<close.lowerBound]
            .trimmingCharacters(in: .whitespaces))
        return isArray ? "[[\(name)]]" : name
    }

    /// The delimiter of a multi-line string that this line opens and leaves open.
    private static func openedMultiline(_ trimmed: String) -> String? {
        for delimiter in ["\"\"\"", "'''"]
        where trimmed.components(separatedBy: delimiter).count % 2 == 0 {
            return delimiter
        }
        return nil
    }

    private static func unquoteKey(_ key: String) -> String {
        if key.count >= 2, let first = key.first, first == key.last, first == "\"" || first == "'" {
            return String(key.dropFirst().dropLast())
        }
        return key
    }

    private static func appendSection(_ output: inout [String], header: String, body: [String]) {
        while let last = output.last, last.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            output.removeLast()
        }
        if !output.isEmpty { output.append("") }
        output.append(header)
        output += body
    }

    func addCorrection(wrong: String, right: String) {
        let w = wrong.trimmingCharacters(in: .whitespaces)
        let r = right.trimmingCharacters(in: .whitespaces)
        guard !w.isEmpty, !r.isEmpty, w != r else { return }
        corrections[w] = r
        save()
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

    /// Escape a string value for TOML (inside double quotes).
    /// Only backslashes and literal double-quotes inside the value need escaping.
    private func escape(_ s: String) -> String {
        s.replacingOccurrences(of: "\\", with: "\\\\")
         .replacingOccurrences(of: "\"", with: "\\\"")
    }

}
