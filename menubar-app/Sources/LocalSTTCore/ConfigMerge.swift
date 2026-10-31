import Foundation

// Writing config.toml without losing what the app does not manage (#64).
extension ConfigManager {
    /// Line-based merge, no TOML library: the app writes only flat string,
    /// number and bool keys. Lines inside multi-line strings and arrays are
    /// left as is.
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
        var scanner = TomlValueScanner()
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

            if scanner.isOpen {
                if !dropContinuation { output.append(line) }
                scanner.scan(trimmed)
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
                // Entries are replaced; comments and blank lines stay, so
                // notes and the spacing before the next section do not change.
                if trimmed.isEmpty || trimmed.hasPrefix("#") { output.append(line) }
                scanner.scan(trimmed)
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
                    scanner.scan(trimmed)
                    dropContinuation = true
                    continue
                }
            }
            output.append(line)
            scanner.scan(trimmed)
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
}

/// Tracks whether a TOML value is still open at the end of a line: inside a
/// multi-line string or an array or inline table spanning lines. Comments and
/// one-line strings are skipped, so `#` and quotes in them change nothing.
struct TomlValueScanner {
    private var multilineDelimiter: [Character]?
    private var depth = 0

    var isOpen: Bool { multilineDelimiter != nil || depth > 0 }

    mutating func scan(_ line: String) {
        let chars = Array(line)
        var i = 0
        func starts(_ token: [Character], at index: Int) -> Bool {
            index + token.count <= chars.count && Array(chars[index..<index + token.count]) == token
        }
        while i < chars.count {
            if let delimiter = multilineDelimiter {
                if delimiter == ["\"", "\"", "\""], chars[i] == "\\" {
                    i += 2
                } else if starts(delimiter, at: i) {
                    multilineDelimiter = nil
                    i += 3
                } else {
                    i += 1
                }
                continue
            }
            let c = chars[i]
            if c == "#" { return }
            if starts(["\"", "\"", "\""], at: i) || starts(["'", "'", "'"], at: i) {
                multilineDelimiter = Array(chars[i..<i + 3])
                i += 3
                continue
            }
            if c == "\"" || c == "'" {
                i += 1
                while i < chars.count, chars[i] != c {
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
