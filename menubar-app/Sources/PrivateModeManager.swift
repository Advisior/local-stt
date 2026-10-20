import Foundation
import Combine

/// Private mode state, persisted in `private_mode.json` in the config dir.
///
/// Format: `{"until": "<ISO-8601 UTC>"}` or `{"until": null}` (until turned
/// off). No file means off. The daemon reads the file before every dictation
/// and treats an unreadable or malformed file as on; the app does the same so
/// the menu always offers "Turn off".
final class PrivateModeManager: ObservableObject {
    @Published private(set) var isActive = false
    /// End time, or nil while active means "until turned off".
    @Published private(set) var until: Date?
    @Published private(set) var now = Date()

    private var timer: Timer?

    static var stateURL: URL { ConfigManager.configDir.appendingPathComponent("private_mode.json") }

    private static let formatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        f.timeZone = TimeZone(identifier: "UTC")
        return f
    }()

    init() {
        refresh()
        let timer = Timer(timeInterval: 1, repeats: true) { [weak self] _ in self?.refresh() }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
    }

    deinit { timer?.invalidate() }

    /// Turn on for `duration` seconds, or until turned off when nil.
    func enable(duration: TimeInterval?) {
        let value: Any = duration.map { Self.formatter.string(from: Date().addingTimeInterval($0)) } ?? NSNull()
        guard let data = try? JSONSerialization.data(withJSONObject: ["until": value]) else { return }
        try? FileManager.default.createDirectory(at: ConfigManager.configDir, withIntermediateDirectories: true)
        try? data.write(to: Self.stateURL, options: .atomic)
        refresh()
    }

    func disable() {
        try? FileManager.default.removeItem(at: Self.stateURL)
        refresh()
    }

    /// "12:34 left", "1:02:03 left" or "On" for "until turned off".
    var statusText: String {
        guard let until = until else { return "On" }
        let remaining = max(0, Int(until.timeIntervalSince(now).rounded(.up)))
        let h = remaining / 3600, m = (remaining % 3600) / 60, s = remaining % 60
        let clock = h > 0 ? String(format: "%d:%02d:%02d", h, m, s) : String(format: "%d:%02d", m, s)
        return "\(clock) left"
    }

    private func refresh() {
        let current = Date()
        let state = Self.readState(now: current)
        if state.expired {
            // Duration elapsed: end private mode for good.
            try? FileManager.default.removeItem(at: Self.stateURL)
        }
        if isActive != state.active { isActive = state.active }
        if until != state.until { until = state.until }
        if state.active { now = current }
    }

    private static func readState(now: Date) -> (active: Bool, until: Date?, expired: Bool) {
        guard FileManager.default.fileExists(atPath: stateURL.path) else { return (false, nil, false) }
        guard let data = try? Data(contentsOf: stateURL),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let raw = json["until"]
        else { return (true, nil, false) }  // fail closed, like the daemon
        if raw is NSNull { return (true, nil, false) }
        guard let string = raw as? String, let end = formatter.date(from: string) else {
            return (true, nil, false)
        }
        return end > now ? (true, end, false) : (false, nil, true)
    }
}
