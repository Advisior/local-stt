import Foundation

// Keys the daemon reads from config.toml but the app does not edit (#51).
// save() rebuilds config.toml from scratch, so it copies these lines from the
// file on disk; without that, any save from Settings or History drops them.
extension ConfigManager {
    static let preservedKeys: Set<String> = ["vocabulary", "vocabulary_from_corrections"]

    /// Lines of `preservedKeys` in the `[claude-stt]` section of `content`,
    /// verbatim and in file order. A multi-line array is copied up to its
    /// closing bracket.
    static func preservedLines(in content: String) -> [String] {
        var result: [String] = []
        var section = ""
        var depth = 0  // unclosed brackets of the value being copied

        for line in content.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if depth > 0 {
                result.append(line)
                depth = max(0, depth + bracketBalance(trimmed))
                continue
            }
            if trimmed.hasPrefix("[") {
                // Outside a value, a line starting with "[" is a table header.
                section = trimmed.dropFirst()
                    .prefix(while: { $0 != "]" })
                    .trimmingCharacters(in: .whitespaces)
                continue
            }
            guard section == "claude-stt", !trimmed.hasPrefix("#"),
                  let eq = trimmed.firstIndex(of: "=") else { continue }
            let key = trimmed[..<eq]
                .trimmingCharacters(in: .whitespaces)
                .trimmingCharacters(in: CharacterSet(charactersIn: "\"'"))
            guard preservedKeys.contains(key) else { continue }
            result.append(line)
            depth = max(0, bracketBalance(String(trimmed[trimmed.index(after: eq)...])))
        }
        return result
    }

    /// Count of "[" minus "]" outside strings and comments.
    private static func bracketBalance(_ text: String) -> Int {
        var balance = 0
        var quote: Character?
        var escaped = false
        for c in text {
            if let open = quote {
                if escaped {
                    escaped = false
                } else if c == "\\" && open == "\"" {
                    escaped = true
                } else if c == open {
                    quote = nil
                }
                continue
            }
            switch c {
            case "\"", "'": quote = c
            case "#": return balance
            case "[": balance += 1
            case "]": balance -= 1
            default: break
            }
        }
        return balance
    }
}
