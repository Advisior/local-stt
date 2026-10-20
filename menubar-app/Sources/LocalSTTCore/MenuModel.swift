import Foundation

/// Lifecycle of the dictation service (the Python daemon) as the app sees it.
enum ServiceState: Equatable {
    case starting, running, stopped
}

/// Durations offered in the Private Mode submenu.
enum PrivateModeDuration: String, Equatable, CaseIterable {
    case fifteenMinutes, oneHour, untilTurnedOff

    var seconds: TimeInterval? {
        switch self {
        case .fifteenMinutes: return 15 * 60
        case .oneHour: return 60 * 60
        case .untilTurnedOff: return nil
        }
    }

    var menuTitle: String {
        switch self {
        case .fifteenMinutes: return "For 15 Minutes"
        case .oneHour: return "For 1 Hour"
        case .untilTurnedOff: return "Until I Turn It Off"
        }
    }

    /// The duration the user chose, if it can be known. `private_mode.json`
    /// stores only the end time, so a timed duration is known only when the
    /// app recorded the choice for exactly that end time.
    static func resolve(isActive: Bool, until: Date?, record: PrivateModeRecord?) -> PrivateModeDuration? {
        guard isActive else { return nil }
        guard let until else { return .untilTurnedOff }
        guard let record, record.duration != .untilTurnedOff, record.until == until else { return nil }
        return record.duration
    }
}

/// The app's note of which timed duration produced which end time.
struct PrivateModeRecord: Equatable {
    let duration: PrivateModeDuration
    let until: Date
}

struct PrivateModeStatus: Equatable {
    var isActive: Bool
    /// Seconds left, nil while active means until turned off.
    var remainingSeconds: Int?
    var duration: PrivateModeDuration?

    static let off = PrivateModeStatus(isActive: false, remainingSeconds: nil, duration: nil)
}

/// Everything the status item menu depends on.
struct MenuState: Equatable {
    var service: ServiceState
    var permissionsReady: Bool
    var privateMode: PrivateModeStatus
    /// "MLX Whisper · Large v3 Turbo"
    var engineSummary: String
    /// Global dictation hotkey, "⌃⇧Space"
    var hotkeyLabel: String
}

enum MenuAction: Equatable {
    case toggleRecording
    case enablePrivateMode(PrivateModeDuration)
    case disablePrivateMode
    case openHistory
    case openSettings
    case startService
    case restartService
    case stopService
    case openLog
    case openPermissions
    case quit
}

/// One row of the status item menu, independent of AppKit.
struct MenuItemSpec: Equatable {
    enum Kind: Equatable { case header, sectionHeader, item, separator }

    var id: String
    var kind: Kind = .item
    var title: String = ""
    var subtitle: String?
    var symbol: String?
    var action: MenuAction?
    var isEnabled = true
    var isChecked = false
    var keyEquivalent = ""
    var submenu: [MenuItemSpec]?

    static func separator(_ id: String) -> MenuItemSpec {
        MenuItemSpec(id: id, kind: .separator, isEnabled: false)
    }
}

/// Pure mapping from app state to the status item menu.
enum MenuModel {
    static func items(for state: MenuState) -> [MenuItemSpec] {
        var items: [MenuItemSpec] = [header(for: state), .separator("sep.header")]

        items.append(MenuItemSpec(
            id: "startDictation",
            title: state.hotkeyLabel.isEmpty ? "Start Dictation" : "Start Dictation (\(state.hotkeyLabel))",
            action: .toggleRecording,
            isEnabled: state.service == .running
        ))
        if state.service == .running && !state.permissionsReady {
            items.append(MenuItemSpec(
                id: "permissions",
                title: "Permissions Needed\u{2026}",
                symbol: "exclamationmark.triangle",
                action: .openPermissions
            ))
        }
        items.append(MenuItemSpec(id: "privateMode", title: "Private Mode", submenu: privateModeItems(state.privateMode)))

        items.append(.separator("sep.navigation"))
        items.append(MenuItemSpec(id: "history", title: "History\u{2026}", action: .openHistory))
        items.append(MenuItemSpec(id: "settings", title: "Settings\u{2026}", action: .openSettings, keyEquivalent: ","))

        items.append(.separator("sep.service"))
        items.append(MenuItemSpec(id: "serviceHeader", kind: .sectionHeader, title: "Dictation Service", isEnabled: false))
        switch state.service {
        case .stopped:
            items.append(MenuItemSpec(id: "serviceStart", title: "Start", action: .startService))
        case .starting:
            items.append(MenuItemSpec(id: "serviceStart", title: "Start", action: .startService, isEnabled: false))
        case .running:
            items.append(MenuItemSpec(id: "serviceRestart", title: "Restart", action: .restartService))
            items.append(MenuItemSpec(id: "serviceStop", title: "Stop", action: .stopService))
        }
        items.append(MenuItemSpec(id: "openLog", title: "Open Log\u{2026}", action: .openLog))

        items.append(.separator("sep.quit"))
        items.append(MenuItemSpec(id: "quit", title: "Quit Local-STT", action: .quit, keyEquivalent: "q"))
        return items
    }

    /// "14:32" or "1:02:03"; negative input counts as zero.
    static func formatRemaining(_ seconds: Int) -> String {
        let s = max(0, seconds)
        let h = s / 3600, m = (s % 3600) / 60, sec = s % 60
        return h > 0 ? String(format: "%d:%02d:%02d", h, m, sec) : String(format: "%d:%02d", m, sec)
    }

    private static func header(for state: MenuState) -> MenuItemSpec {
        var header = MenuItemSpec(id: "header", kind: .header, isEnabled: false)
        switch state.service {
        case .starting:
            header.title = "Starting\u{2026}"
            header.symbol = "hourglass"
        case .stopped:
            header.title = "Dictation Service Stopped"
            header.symbol = "mic.slash"
        case .running:
            header.subtitle = state.engineSummary.isEmpty ? nil : state.engineSummary
            if state.privateMode.isActive {
                header.title = state.privateMode.remainingSeconds
                    .map { "Private Mode \u{00B7} \(formatRemaining($0)) Left" } ?? "Private Mode On"
                header.symbol = "eye.slash"
            } else {
                header.title = "Ready to Dictate"
                header.symbol = "mic"
            }
        }
        return header
    }

    private static func privateModeItems(_ status: PrivateModeStatus) -> [MenuItemSpec] {
        var items = PrivateModeDuration.allCases.map { duration in
            MenuItemSpec(
                id: "privateMode.\(duration.rawValue)",
                title: duration.menuTitle,
                action: .enablePrivateMode(duration),
                isChecked: status.isActive && status.duration == duration
            )
        }
        guard status.isActive else { return items }
        items.append(.separator("sep.privateMode"))
        if let remaining = status.remainingSeconds {
            items.append(MenuItemSpec(
                id: "privateModeRemaining",
                title: "\(formatRemaining(remaining)) Left",
                isEnabled: false
            ))
        }
        items.append(MenuItemSpec(id: "privateModeOff", title: "Turn Off Private Mode", action: .disablePrivateMode))
        return items
    }
}
