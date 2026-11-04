import Foundation

// Keys the daemon reads from config.toml but the app does not edit (#51).
// save() rebuilds config.toml from scratch, so it copies these lines from the
// file on disk; without that, any save from Settings or History drops them.
extension ConfigManager {
    static let preservedKeys: Set<String> = ["vocabulary", "vocabulary_from_corrections"]

    /// Lines of `preservedKeys` in the `[claude-stt]` section of `content`,
    /// verbatim and in file order. A value spanning lines (array, multi-line
    /// string) is copied up to its end. Continuation lines of other keys'
    /// values are never read as headers or keys.
    static func preservedLines(in content: String) -> [String] {
        var result: [String] = []
        var section = ""
        var scanner = PreservedValueScanner()
        var copying = false

        for line in content.components(separatedBy: .newlines) {
            if scanner.isOpen {
                if copying { result.append(line) }
                scanner.scan(line)
                continue
            }
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.hasPrefix("[") {
                // Outside a value, a line starting with "[" is a table header.
                section = trimmed.dropFirst()
                    .prefix(while: { $0 != "]" })
                    .trimmingCharacters(in: .whitespaces)
                continue
            }
            guard !trimmed.hasPrefix("#"), let eq = trimmed.firstIndex(of: "=") else { continue }
            let key = trimmed[..<eq]
                .trimmingCharacters(in: .whitespaces)
                .trimmingCharacters(in: CharacterSet(charactersIn: "\"'"))
            copying = section == "claude-stt" && preservedKeys.contains(key)
            if copying { result.append(line) }
            scanner.scan(String(trimmed[trimmed.index(after: eq)...]))
        }
        return result
    }
}

/// Tracks whether a TOML value is still open at the end of a line: inside an
/// array or inline table, or inside a multi-line string. The state carries
/// over between lines; one-line strings and comments are skipped, so quotes,
/// brackets and "#" inside them change nothing.
struct PreservedValueScanner {
    private var multilineQuote: Character?  // " or ' while inside """ or '''
    private var depth = 0

    var isOpen: Bool { depth > 0 || multilineQuote != nil }

    mutating func scan(_ line: String) {
        let chars = Array(line)
        func isTriple(_ quote: Character, at index: Int) -> Bool {
            index + 2 < chars.count
                && chars[index] == quote && chars[index + 1] == quote && chars[index + 2] == quote
        }
        var i = 0
        while i < chars.count {
            let c = chars[i]
            if let quote = multilineQuote {
                if quote == "\"" && c == "\\" {
                    i += 2
                } else if isTriple(quote, at: i) {
                    multilineQuote = nil
                    i += 3
                } else {
                    i += 1
                }
                continue
            }
            if c == "#" { return }
            if c == "\"" || c == "'" {
                if isTriple(c, at: i) {
                    multilineQuote = c
                    i += 3
                    continue
                }
                i += 1
                while i < chars.count && chars[i] != c {
                    i += (c == "\"" && chars[i] == "\\") ? 2 : 1
                }
                i += 1
                continue
            }
            if c == "[" || c == "{" { depth += 1 }
            if c == "]" || c == "}" { depth = max(0, depth - 1) }
            i += 1
        }
    }
}
