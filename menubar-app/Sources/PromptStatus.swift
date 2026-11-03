import Foundation

/// What the daemon left out of Whisper's prompt (#51). The daemon writes
/// `prompt_status.json` next to `config.toml` whenever the prompt changes.
struct PromptStatus: Decodable {
    let budget: Int
    let hintOverBudget: Bool
    let dropped: [String]

    enum CodingKeys: String, CodingKey {
        case budget
        case hintOverBudget = "hint_over_budget"
        case dropped
    }

    static func load() -> PromptStatus? {
        let url = ConfigManager.configDir.appendingPathComponent("prompt_status.json")
        guard let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(PromptStatus.self, from: data)
    }

    /// Warning for Settings, or nil when everything fit.
    var warning: String? {
        if hintOverBudget {
            return "This prompt is longer than Whisper's \(budget) tokens, so Whisper cuts its beginning. Move proper nouns to vocabulary.toml."
        }
        if !dropped.isEmpty {
            return "\(dropped.count) vocabulary term(s) did not fit Whisper's \(budget)-token prompt and were left out: \(dropped.joined(separator: ", "))"
        }
        return nil
    }
}
