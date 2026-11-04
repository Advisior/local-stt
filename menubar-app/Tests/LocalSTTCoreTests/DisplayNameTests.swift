import Testing
@testable import LocalSTTCore

@Suite struct DisplayNameTests {
    @Test("AC-2: given an engine id, when shown in the header, then its display name is used",
          arguments: [("mlx", "MLX Whisper"), ("whisper", "Whisper"), ("parakeet", "Parakeet"), ("moonshine", "Moonshine")])
    func engineNames(id: String, name: String) {
        #expect(ConfigManager.engineDisplayName(id) == name)
    }

    @Test("AC-2: given a model id, when shown in the header, then prefixes and suffixes are dropped and words are title case",
          arguments: [
            ("large-v3-turbo", "Large v3 Turbo"),
            ("mlx-community/whisper-large-v3-mlx", "Large v3"),
            ("mlx-community/whisper-large-v3-turbo", "Large v3 Turbo"),
            ("medium", "Medium"),
            ("moonshine/base", "Base"),
            ("tdt-0.6b-v3", "TDT 0.6B v3"),
            ("", ""),
          ])
    func modelNames(id: String, name: String) {
        #expect(ConfigManager.modelDisplayName(id) == name)
    }

    @Test("AC-2: given the running config, when the header subtitle is built, then engine and active model are joined by a middle dot")
    func summary() {
        let config = ConfigManager(loadFromDisk: false)
        config.engine = "mlx"
        config.whisperModel = "large-v3-turbo"
        #expect(config.serviceSummary == "MLX Whisper \u{00B7} Large v3 Turbo")
        config.engine = "parakeet"
        config.parakeetModel = "tdt-0.6b-v3"
        #expect(config.serviceSummary == "Parakeet \u{00B7} TDT 0.6B v3")
        #expect(config.engineLabel == "parakeet (tdt-0.6b-v3)")
    }
}
