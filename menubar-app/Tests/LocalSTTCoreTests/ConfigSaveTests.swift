import Foundation
import Testing
@testable import LocalSTTCore

/// Every test writes into its own temp dir; the real ~/.config/local-stt is never touched.
private func tempConfigDir() throws -> URL {
    let dir = FileManager.default.temporaryDirectory
        .appendingPathComponent("LocalSTTConfigTests-\(UUID().uuidString)")
    try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    return dir
}

private func writeConfig(_ text: String, in dir: URL) throws {
    try text.write(to: dir.appendingPathComponent("config.toml"), atomically: true, encoding: .utf8)
}

private func readConfig(in dir: URL) throws -> String {
    try String(contentsOf: dir.appendingPathComponent("config.toml"), encoding: .utf8)
}

private func lines(_ text: String) -> [String] {
    text.components(separatedBy: "\n")
}

@Suite struct ConfigSaveTests {
    @Test("AC-1: given unknown keys, comments and other sections, when the app saves, then managed keys change in place and every other line stays byte for byte")
    func keepsUnmanagedLines() throws {
        let dir = try tempConfigDir()
        let original = """
        # top comment
        [claude-stt]
        hotkey = "ctrl+shift+space"
        audio_device = "MacBook Pro Microphone"
        # explain the threshold
        min_audio_db = -60.0

        mode = "toggle"
        min_recording_seconds = 0.4

        [future]
        debug_keep_recordings = true   # keep it

        """
        try writeConfig(original, in: dir)
        let config = ConfigManager(configDirectory: dir)
        config.hotkey = "cmd_r"
        config.mode = "push-to-talk"
        config.save()

        let saved = lines(try readConfig(in: dir))
        #expect(saved[0] == "# top comment")
        #expect(saved[1] == "[claude-stt]")
        #expect(saved[2] == "hotkey = \"cmd_r\"")
        #expect(saved[3] == "audio_device = \"MacBook Pro Microphone\"")
        #expect(saved[4] == "# explain the threshold")
        #expect(saved[5] == "min_audio_db = -60.0")
        #expect(saved[6] == "")
        #expect(saved[7] == "mode = \"push-to-talk\"")
        #expect(saved[8] == "min_recording_seconds = 0.4")
        #expect(saved.contains("[future]"))
        #expect(saved.contains("debug_keep_recordings = true   # keep it"))
        // [future] keeps its position after [claude-stt] and its trailing blank line.
        let futureIndex = try #require(saved.firstIndex(of: "[future]"))
        #expect(saved[futureIndex - 1] == "")
        #expect(saved[futureIndex + 1] == "debug_keep_recordings = true   # keep it")
        #expect(saved.count == futureIndex + 3)
    }

    @Test("AC-1: given managed keys missing from [claude-stt], when the app saves, then they are appended inside that section before the next one")
    func appendsMissingManagedKeys() throws {
        let dir = try tempConfigDir()
        try writeConfig("[claude-stt]\nhotkey = \"f1\"\n\n[corrections]\n\"teh\" = \"the\"\n", in: dir)
        let config = ConfigManager(configDirectory: dir)
        config.save()

        let saved = lines(try readConfig(in: dir))
        let corrections = try #require(saved.firstIndex(of: "[corrections]"))
        let mode = try #require(saved.firstIndex(of: "mode = \"toggle\""))
        let undoMax = try #require(saved.firstIndex(of: "undo_max_chars = 400"))
        #expect(saved[1] == "hotkey = \"f1\"")
        #expect(mode < corrections && undoMax < corrections)
        #expect(saved[corrections - 1] == "")
        #expect(saved.filter { $0.hasPrefix("hotkey") }.count == 1)
    }

    @Test("AC-1: given a file without [claude-stt], when the app saves, then the section is appended and the existing content stays")
    func addsMissingSection() throws {
        let dir = try tempConfigDir()
        try writeConfig("# only comments\n[other]\nx = 1\n", in: dir)
        let config = ConfigManager(configDirectory: dir)
        config.save()

        let saved = try readConfig(in: dir)
        #expect(saved.hasPrefix("# only comments\n[other]\nx = 1\n\n[claude-stt]\n"))
        #expect(lines(saved).contains("hotkey = \"ctrl+shift+space\""))
    }

    @Test("AC-2: given a [corrections] section and a later section, when the app saves, then only the corrections entries are replaced")
    func replacesCorrectionsOnly() throws {
        let dir = try tempConfigDir()
        try writeConfig("""
        [claude-stt]
        hotkey = "f1"

        [corrections]
        "old" = "gone"

        [vocabulary]
        terms = ["Advisior"]

        """, in: dir)
        let config = ConfigManager(configDirectory: dir)
        config.addCorrection(wrong: "b", right: "B")
        config.addCorrection(wrong: "a", right: "A")
        config.corrections.removeValue(forKey: "old")
        config.save()

        let saved = lines(try readConfig(in: dir))
        let corrections = try #require(saved.firstIndex(of: "[corrections]"))
        #expect(Array(saved[corrections...].prefix(5)) == [
            "[corrections]", "\"a\" = \"A\"", "\"b\" = \"B\"", "", "[vocabulary]",
        ])
        #expect(saved.contains("terms = [\"Advisior\"]"))
        #expect(!saved.contains("\"old\" = \"gone\""))
    }

    @Test("AC-2: given corrections become empty, when the app saves, then the corrections entries go and every other section stays")
    func emptyCorrections() throws {
        let dir = try tempConfigDir()
        try writeConfig("[claude-stt]\nhotkey = \"f1\"\n\n[corrections]\n\"x\" = \"y\"\n\n[other]\nk = 2\n", in: dir)
        let config = ConfigManager(configDirectory: dir)
        config.corrections = [:]
        config.save()

        let saved = lines(try readConfig(in: dir))
        #expect(!saved.contains("\"x\" = \"y\""))
        #expect(saved.contains("[other]"))
        #expect(saved.contains("k = 2"))
        #expect(saved.contains("hotkey = \"f1\""))
    }

    @Test("AC-2: given no [corrections] section, when a correction is added, then the section is appended at the end")
    func appendsCorrectionsSection() throws {
        let dir = try tempConfigDir()
        try writeConfig("[claude-stt]\nhotkey = \"f1\"\n", in: dir)
        let config = ConfigManager(configDirectory: dir)
        config.addCorrection(wrong: "teh", right: "the")

        let saved = try readConfig(in: dir)
        #expect(saved.hasSuffix("\n\n[corrections]\n\"teh\" = \"the\"\n"))
    }

    @Test("AC-3: given language and initial_prompt are set in the file, when they are cleared and the app saves, then both key lines are removed")
    func removesEmptyOptionalKeys() throws {
        let dir = try tempConfigDir()
        try writeConfig("[claude-stt]\nlanguage = \"de\"\ninitial_prompt = \"Hallo\"\naudio_device = \"Mic\"\n", in: dir)
        let config = ConfigManager(configDirectory: dir)
        #expect(config.language == "de")
        config.language = ""
        config.initialPrompt = ""
        config.save()

        let saved = lines(try readConfig(in: dir))
        #expect(!saved.contains { $0.hasPrefix("language") })
        #expect(!saved.contains { $0.hasPrefix("initial_prompt") })
        #expect(saved.contains("audio_device = \"Mic\""))
    }

    @Test("AC-4: given custom sample_rate and max_recording_seconds, when the app saves, then those lines stay and none are added")
    func leavesRecorderKeysAlone() throws {
        let dir = try tempConfigDir()
        try writeConfig("[claude-stt]\nsample_rate = 48000\nmax_recording_seconds = 600\n", in: dir)
        ConfigManager(configDirectory: dir).save()

        let saved = lines(try readConfig(in: dir))
        #expect(saved.filter { $0.hasPrefix("sample_rate") } == ["sample_rate = 48000"])
        #expect(saved.filter { $0.hasPrefix("max_recording_seconds") } == ["max_recording_seconds = 600"])
    }

    @Test("AC-5: given no config.toml, when the app saves, then a new file with the managed keys is written")
    func writesNewFile() throws {
        let dir = try tempConfigDir().appendingPathComponent("nested")
        let config = ConfigManager(configDirectory: dir)
        config.language = "de"
        config.save()

        let saved = lines(try readConfig(in: dir))
        #expect(saved.first == "[claude-stt]")
        for key in ["hotkey", "mode", "engine", "moonshine_model", "whisper_model", "parakeet_model",
                    "output_mode", "sound_effects", "auto_start_daemon", "mute_on_record",
                    "undo_hotkey", "undo_window_seconds", "undo_max_chars", "language"] {
            #expect(saved.contains { $0.hasPrefix("\(key) = ") }, "missing \(key)")
        }
        #expect(!saved.contains { $0.hasPrefix("sample_rate") || $0.hasPrefix("max_recording_seconds") })
        #expect(!saved.contains { $0.hasPrefix("initial_prompt") })
        #expect(!saved.contains("[corrections]"))
    }

    @Test("AC-6: given values with quotes and backslashes, when saved and loaded again, then they round-trip unchanged")
    func escapingRoundTrip() throws {
        let dir = try tempConfigDir()
        try writeConfig("[claude-stt]\nhotkey = \"f1\"\n", in: dir)
        let config = ConfigManager(configDirectory: dir)
        config.initialPrompt = #"Say "hi" to C:\Users"#
        config.addCorrection(wrong: #"a "b""#, right: #"c\d"#)

        let reloaded = ConfigManager(configDirectory: dir)
        #expect(reloaded.initialPrompt == #"Say "hi" to C:\Users"#)
        #expect(reloaded.corrections == [#"a "b""#: #"c\d"#])
        #expect(reloaded.hotkey == "f1")
    }

    @Test("AC-6: given an invalid mode, when the app saves, then validation still resets it before writing")
    func validationStillRuns() throws {
        let dir = try tempConfigDir()
        try writeConfig("[claude-stt]\nmode = \"bogus\"\nkeep = 1\n", in: dir)
        let config = ConfigManager(configDirectory: dir)
        config.save()

        let saved = lines(try readConfig(in: dir))
        #expect(saved.contains("mode = \"toggle\""))
        #expect(saved.contains("keep = 1"))
    }

    @Test("AC-1: given a multi-line string in [claude-stt] whose lines look like keys and headers, when the app saves, then its lines stay untouched")
    func keepsMultilineStrings() throws {
        let dir = try tempConfigDir()
        let original = "[claude-stt]\nnote = \"\"\"\nhotkey = \"inside\"\n[fake]\n\"\"\"\nhotkey = \"f1\"\n"
        try writeConfig(original, in: dir)
        let config = ConfigManager(configDirectory: dir)
        config.hotkey = "f2"
        config.save()

        let saved = lines(try readConfig(in: dir))
        #expect(Array(saved.prefix(6)) == [
            "[claude-stt]", "note = \"\"\"", "hotkey = \"inside\"", "[fake]", "\"\"\"", "hotkey = \"f2\"",
        ])
    }

    @Test("AC-1: given a file without a trailing newline, when the app saves, then the last line is kept and the file ends with one newline")
    func noTrailingNewline() throws {
        let dir = try tempConfigDir()
        try writeConfig("[claude-stt]\nhotkey = \"f1\"\n[other]\nlast = 1", in: dir)
        ConfigManager(configDirectory: dir).save()

        let saved = try readConfig(in: dir)
        #expect(saved.hasSuffix("[other]\nlast = 1\n"))
        #expect(!saved.hasSuffix("\n\n"))
    }
}
