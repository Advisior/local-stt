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

    /// The duration behind the current state, when known (see `PrivateModeDuration.resolve`).
    @Published private(set) var duration: PrivateModeDuration?

    private var timer: Timer?
    private let defaults: UserDefaults
    private static let recordDurationKey = "privateModeDuration"
    private static let recordUntilKey = "privateModeUntil"

    static var stateURL: URL { ConfigManager.configDir.appendingPathComponent("private_mode.json") }

    private static let formatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        f.timeZone = TimeZone(identifier: "UTC")
        return f
    }()

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        refresh()
        let timer = Timer(timeInterval: 1, repeats: true) { [weak self] _ in self?.refresh() }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
    }

    deinit { timer?.invalidate() }

    /// Turn on for the chosen duration. The file keeps its format; the choice
    /// itself is noted in the app's defaults for the menu checkmark.
    func enable(_ choice: PrivateModeDuration) {
        let end = choice.seconds.map { Date().addingTimeInterval($0) }
        let value: Any = end.map { Self.formatter.string(from: $0) } ?? NSNull()
        guard let data = try? JSONSerialization.data(withJSONObject: ["until": value]) else { return }
        try? FileManager.default.createDirectory(at: ConfigManager.configDir, withIntermediateDirectories: true)
        try? data.write(to: Self.stateURL, options: .atomic)
        if let end {
            // Store the end time as written, so it compares equal after reading the file back.
            defaults.set(choice.rawValue, forKey: Self.recordDurationKey)
            defaults.set(Self.formatter.string(from: end), forKey: Self.recordUntilKey)
        }
        refresh()
    }

    /// Snapshot for the status menu.
    var status: PrivateModeStatus {
        guard isActive else { return .off }
        let remaining = until.map { max(0, Int($0.timeIntervalSince(now).rounded(.up))) }
        return PrivateModeStatus(isActive: true, remainingSeconds: remaining, duration: duration)
    }

    func disable() {
        try? FileManager.default.removeItem(at: Self.stateURL)
        refresh()
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
        let resolved = PrivateModeDuration.resolve(
            isActive: state.active, until: state.until, record: record, malformed: state.malformed
        )
        if duration != resolved { duration = resolved }
        if state.active { now = current }
    }

    private var record: PrivateModeRecord? {
        guard let raw = defaults.string(forKey: Self.recordDurationKey),
              let duration = PrivateModeDuration(rawValue: raw),
              let untilString = defaults.string(forKey: Self.recordUntilKey),
              let until = Self.formatter.date(from: untilString)
        else { return nil }
        return PrivateModeRecord(duration: duration, until: until)
    }

    private static func readState(now: Date) -> (active: Bool, until: Date?, expired: Bool, malformed: Bool) {
        guard FileManager.default.fileExists(atPath: stateURL.path) else { return (false, nil, false, false) }
        guard let data = try? Data(contentsOf: stateURL),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let raw = json["until"]
        else { return (true, nil, false, true) }  // fail closed, like the daemon
        if raw is NSNull { return (true, nil, false, false) }
        guard let string = raw as? String, let end = formatter.date(from: string) else {
            return (true, nil, false, true)
        }
        return end > now ? (true, end, false, false) : (false, nil, true, false)
    }
}
