import Foundation

/// Writes to `history.jsonl` from the app side.
///
/// The daemon (`claude_stt/history.py`) appends under the same exclusive
/// `flock` on `history.lock` and replaces the file atomically, so a delete
/// here and a new dictation there never overwrite each other.
enum HistoryStore {
    static var historyURL: URL { ConfigManager.configDir.appendingPathComponent("history.jsonl") }
    static var lockURL: URL { ConfigManager.configDir.appendingPathComponent("history.lock") }

    /// Remove the first line whose timestamp and text match. Other lines are
    /// kept byte for byte. Returns false and changes nothing if no line matches.
    @discardableResult
    static func deleteEntry(timestamp: String, text: String) -> Bool {
        let fd = open(lockURL.path, O_RDWR | O_CREAT, 0o600)
        guard fd >= 0 else { return false }
        defer { close(fd) }
        guard flock(fd, LOCK_EX) == 0 else { return false }
        defer { flock(fd, LOCK_UN) }

        guard let content = try? String(contentsOf: historyURL, encoding: .utf8) else { return false }
        var lines = content
            .split(separator: "\n", omittingEmptySubsequences: true)
            .map(String.init)
            .filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
        guard let index = lines.firstIndex(where: { matches($0, timestamp: timestamp, text: text) }) else {
            return false
        }
        lines.remove(at: index)
        return writeAtomically(lines)
    }

    private static func matches(_ line: String, timestamp: String, text: String) -> Bool {
        guard let data = line.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return false }
        return json["timestamp"] as? String == timestamp && json["text"] as? String == text
    }

    /// Same line format as the daemon: one JSON object per line, each ending in "\n".
    private static func writeAtomically(_ lines: [String]) -> Bool {
        let body = lines.map { $0 + "\n" }.joined()
        let tmpURL = ConfigManager.configDir.appendingPathComponent(".history.\(UUID().uuidString).tmp")
        do {
            try Data(body.utf8).write(to: tmpURL, options: .withoutOverwriting)
        } catch {
            return false
        }
        if rename(tmpURL.path, historyURL.path) != 0 {
            try? FileManager.default.removeItem(at: tmpURL)
            return false
        }
        return true
    }
}
