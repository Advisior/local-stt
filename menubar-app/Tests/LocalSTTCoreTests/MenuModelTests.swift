import AppKit
import Testing
@testable import LocalSTTCore

private func state(
    _ service: ServiceState = .running,
    permissionsReady: Bool = true,
    privateMode: PrivateModeStatus = .off,
    summary: String = "MLX Whisper \u{00B7} Large v3 Turbo",
    hotkey: String = "\u{2303}\u{21E7}Space"
) -> MenuState {
    MenuState(service: service, permissionsReady: permissionsReady, privateMode: privateMode,
              engineSummary: summary, hotkeyLabel: hotkey)
}

private func item(_ id: String, in items: [MenuItemSpec]) -> MenuItemSpec? {
    for item in items {
        if item.id == id { return item }
        if let found = item.submenu.flatMap({ sub in sub.first { $0.id == id } }) { return found }
    }
    return nil
}

private func allItems(_ items: [MenuItemSpec]) -> [MenuItemSpec] {
    items.flatMap { [$0] + ($0.submenu ?? []) }
}

@Suite struct MenuHeaderTests {
    @Test("AC-2: given the service runs, when the menu opens, then the header shows Ready to Dictate with engine and model")
    func readyHeader() throws {
        let header = try #require(MenuModel.items(for: state()).first)
        #expect(header.kind == .header)
        #expect(header.action == nil)
        #expect(header.isEnabled == false)
        #expect(header.title == "Ready to Dictate")
        #expect(header.subtitle == "MLX Whisper \u{00B7} Large v3 Turbo")
        #expect(header.symbol != nil)
    }

    @Test("AC-2: given each service state, when the menu opens, then the header has its own title and SF Symbol and no engine line unless running")
    func headerPerState() throws {
        let starting = try #require(MenuModel.items(for: state(.starting)).first)
        let stopped = try #require(MenuModel.items(for: state(.stopped)).first)
        let ready = try #require(MenuModel.items(for: state(.running)).first)
        let privateOn = try #require(MenuModel.items(for: state(
            privateMode: PrivateModeStatus(isActive: true, remainingSeconds: 14 * 60 + 32, duration: .fifteenMinutes)
        )).first)
        #expect(starting.title == "Starting\u{2026}")
        #expect(stopped.title == "Dictation Service Stopped")
        #expect(privateOn.title == "Private Mode \u{00B7} 14:32 Left")
        #expect(starting.subtitle == nil)
        #expect(stopped.subtitle == nil)
        #expect(privateOn.subtitle == "MLX Whisper \u{00B7} Large v3 Turbo")
        let symbols = Set([starting, stopped, ready, privateOn].compactMap(\.symbol))
        #expect(symbols.count == 4)
    }

    @Test("AC-2: given private mode until turned off, when the menu opens, then the header names private mode without a countdown")
    func privateUntilOffHeader() throws {
        let header = try #require(MenuModel.items(for: state(
            privateMode: PrivateModeStatus(isActive: true, remainingSeconds: nil, duration: .untilTurnedOff)
        )).first)
        #expect(header.title == "Private Mode On")
    }

    @Test("AC-2: given remaining seconds, when formatted, then minutes and seconds or hours are shown")
    func remainingFormat() {
        #expect(MenuModel.formatRemaining(0) == "0:00")
        #expect(MenuModel.formatRemaining(59) == "0:59")
        #expect(MenuModel.formatRemaining(14 * 60 + 32) == "14:32")
        #expect(MenuModel.formatRemaining(3600) == "1:00:00")
        #expect(MenuModel.formatRemaining(-5) == "0:00")
    }
}

@Suite struct StartDictationTests {
    @Test("AC-3: given the service runs, when the menu opens, then Start Dictation is enabled, names the hotkey and toggles recording")
    func enabledWhileRunning() throws {
        let start = try #require(item("startDictation", in: MenuModel.items(for: state())))
        #expect(start.title == "Start Dictation (\u{2303}\u{21E7}Space)")
        #expect(start.isEnabled)
        #expect(start.action == .toggleRecording)
    }

    @Test("AC-3: given the service is stopped or starting, when the menu opens, then Start Dictation is disabled")
    func disabledOtherwise() throws {
        for service in [ServiceState.stopped, .starting] {
            let start = try #require(item("startDictation", in: MenuModel.items(for: state(service))))
            #expect(start.isEnabled == false)
        }
    }

    @Test("AC-3: given an empty hotkey label, when the menu opens, then the title has no empty parentheses")
    func emptyHotkey() throws {
        let start = try #require(item("startDictation", in: MenuModel.items(for: state(hotkey: ""))))
        #expect(start.title == "Start Dictation")
    }
}

@Suite struct PrivateModeMenuTests {
    @Test("AC-4: given private mode is off, when the submenu opens, then it offers the three durations without checkmarks or turn off")
    func offeredWhenOff() throws {
        let sub = try #require(item("privateMode", in: MenuModel.items(for: state()))?.submenu)
        #expect(sub.filter { $0.kind == .item }.map(\.title) == ["For 15 Minutes", "For 1 Hour", "Until I Turn It Off"])
        #expect(sub.allSatisfy { !$0.isChecked })
        #expect(sub[0].action == .enablePrivateMode(.fifteenMinutes))
        #expect(sub[1].action == .enablePrivateMode(.oneHour))
        #expect(sub[2].action == .enablePrivateMode(.untilTurnedOff))
    }

    @Test("AC-4: given private mode is active for 1 hour, when the submenu opens, then 1 Hour is checked, the remaining time shows disabled and Turn Off is offered")
    func activeTimed() throws {
        let status = PrivateModeStatus(isActive: true, remainingSeconds: 59 * 60 + 1, duration: .oneHour)
        let sub = try #require(item("privateMode", in: MenuModel.items(for: state(privateMode: status)))?.submenu)
        #expect(sub.first { $0.title == "For 1 Hour" }?.isChecked == true)
        #expect(sub.filter(\.isChecked).count == 1)
        let remaining = try #require(sub.first { $0.id == "privateModeRemaining" })
        #expect(remaining.title == "59:01 Left")
        #expect(remaining.isEnabled == false)
        let off = try #require(sub.first { $0.title == "Turn Off Private Mode" })
        #expect(off.action == .disablePrivateMode)
        #expect(off.isEnabled)
    }

    @Test("AC-4: given private mode until turned off, when the submenu opens, then Until I Turn It Off is checked and no countdown shows")
    func activeUntilOff() throws {
        let status = PrivateModeStatus(isActive: true, remainingSeconds: nil, duration: .untilTurnedOff)
        let sub = try #require(item("privateMode", in: MenuModel.items(for: state(privateMode: status)))?.submenu)
        #expect(sub.first { $0.title == "Until I Turn It Off" }?.isChecked == true)
        #expect(sub.contains { $0.id == "privateModeRemaining" } == false)
        #expect(sub.contains { $0.title == "Turn Off Private Mode" })
    }

    @Test("AC-4: given a timed private mode of unknown duration, when the submenu opens, then nothing is checked but the countdown shows")
    func activeUnknownDuration() throws {
        let status = PrivateModeStatus(isActive: true, remainingSeconds: 90, duration: nil)
        let sub = try #require(item("privateMode", in: MenuModel.items(for: state(privateMode: status)))?.submenu)
        #expect(sub.allSatisfy { !$0.isChecked })
        #expect(sub.first { $0.id == "privateModeRemaining" }?.title == "1:30 Left")
    }

    @Test("AC-4: given a recorded duration, when resolved against the current end time, then it matches only that end time")
    func durationResolution() {
        let end = Date(timeIntervalSince1970: 1_000_000)
        let record = PrivateModeRecord(duration: .oneHour, until: end)
        #expect(PrivateModeDuration.resolve(isActive: false, until: nil, record: record) == nil)
        #expect(PrivateModeDuration.resolve(isActive: true, until: nil, record: record) == .untilTurnedOff)
        #expect(PrivateModeDuration.resolve(isActive: true, until: end, record: record) == .oneHour)
        #expect(PrivateModeDuration.resolve(isActive: true, until: end.addingTimeInterval(60), record: record) == nil)
        #expect(PrivateModeDuration.resolve(isActive: true, until: end, record: nil) == nil)
    }
}

@Suite struct ServiceSectionTests {
    private func section(_ service: ServiceState) -> [MenuItemSpec] {
        let items = MenuModel.items(for: state(service))
        let start = items.firstIndex { $0.id == "serviceHeader" }!
        return Array(items[start...]).prefix { $0.kind != .separator }.map { $0 }
    }

    @Test("AC-7: given the service is stopped, when the menu opens, then the Dictation Service section offers Start and Open Log")
    func stopped() {
        let s = section(.stopped)
        #expect(s.first?.kind == .sectionHeader)
        #expect(s.first?.title == "Dictation Service")
        #expect(s.dropFirst().map(\.title) == ["Start", "Open Log\u{2026}"])
        #expect(s.first { $0.title == "Start" }?.action == .startService)
        #expect(s.dropFirst().allSatisfy { $0.isEnabled })
    }

    @Test("AC-7: given the service runs, when the menu opens, then the section offers Restart, Stop and Open Log")
    func running() {
        let s = section(.running)
        #expect(s.dropFirst().map(\.title) == ["Restart", "Stop", "Open Log\u{2026}"])
        #expect(s.first { $0.title == "Restart" }?.action == .restartService)
        #expect(s.first { $0.title == "Stop" }?.action == .stopService)
        #expect(s.dropFirst().allSatisfy { $0.isEnabled })
    }

    @Test("AC-7: given the service is starting, when the menu opens, then the service controls are disabled and Open Log stays enabled")
    func starting() {
        let s = section(.starting)
        let controls = s.dropFirst().filter { $0.title != "Open Log\u{2026}" }
        #expect(controls.isEmpty == false)
        #expect(controls.allSatisfy { !$0.isEnabled })
        #expect(s.first { $0.title == "Open Log\u{2026}" }?.action == .openLog)
        #expect(s.first { $0.title == "Open Log\u{2026}" }?.isEnabled == true)
    }
}

@Suite struct NavigationItemTests {
    @Test("AC-5, AC-6, AC-8: given any state, when the menu opens, then History, Settings with command-comma and Quit with command-Q are present")
    func navigation() throws {
        for service in [ServiceState.stopped, .starting, .running] {
            let items = MenuModel.items(for: state(service))
            let history = try #require(item("history", in: items))
            #expect(history.title == "History\u{2026}")
            #expect(history.action == .openHistory)
            let settings = try #require(item("settings", in: items))
            #expect(settings.title == "Settings\u{2026}")
            #expect(settings.action == .openSettings)
            #expect(settings.keyEquivalent == ",")
            let quit = try #require(items.last)
            #expect(quit.title == "Quit Local-STT")
            #expect(quit.action == .quit)
            #expect(quit.keyEquivalent == "q")
        }
    }
}

@Suite struct PermissionItemTests {
    @Test("AC-9: given the service runs and permissions are missing, when the menu opens, then Permissions Needed opens System Settings")
    func shownWhenMissing() throws {
        let perm = try #require(item("permissions", in: MenuModel.items(for: state(permissionsReady: false))))
        #expect(perm.title == "Permissions Needed\u{2026}")
        #expect(perm.action == .openPermissions)
        #expect(perm.isEnabled)
    }

    @Test("AC-9: given permissions are fine or the service is stopped, when the menu opens, then no permissions item shows")
    func hiddenOtherwise() {
        #expect(item("permissions", in: MenuModel.items(for: state())) == nil)
        #expect(item("permissions", in: MenuModel.items(for: state(.stopped, permissionsReady: false))) == nil)
    }
}

@Suite struct EllipsisTests {
    @Test("AC-10: given every state, when the menu opens, then no label contains three periods")
    func noThreePeriods() {
        let statuses: [PrivateModeStatus] = [
            .off,
            PrivateModeStatus(isActive: true, remainingSeconds: 100, duration: .fifteenMinutes),
            PrivateModeStatus(isActive: true, remainingSeconds: nil, duration: .untilTurnedOff),
        ]
        for service in [ServiceState.stopped, .starting, .running] {
            for ready in [true, false] {
                for status in statuses {
                    let labels = allItems(MenuModel.items(for: state(service, permissionsReady: ready, privateMode: status)))
                        .flatMap { [$0.title, $0.subtitle ?? ""] }
                    #expect(labels.allSatisfy { !$0.contains("...") })
                }
            }
        }
    }
}

@Suite @MainActor struct StatusMenuBuilderTests {
    @Test("AC-1: given menu specs, when the NSMenu is built, then titles, enabled state, checkmarks, key equivalents and submenus carry over")
    func buildsNSMenu() throws {
        let status = PrivateModeStatus(isActive: true, remainingSeconds: 600, duration: .fifteenMinutes)
        let specs = MenuModel.items(for: state(privateMode: status))
        let menu = NSMenu()
        StatusMenuBuilder.populate(menu, with: specs, target: nil, action: nil)
        #expect(menu.items.count == specs.count)
        #expect(menu.autoenablesItems == false)
        let settings = try #require(menu.items.first { $0.title == "Settings\u{2026}" })
        #expect(settings.keyEquivalent == ",")
        #expect(settings.keyEquivalentModifierMask == .command)
        let header = try #require(menu.items.first)
        #expect(header.isEnabled == false)
        #expect(header.title == "Private Mode \u{00B7} 10:00 Left")
        #expect(header.image != nil)
        let privateItem = try #require(menu.items.first { $0.title == "Private Mode" })
        let sub = try #require(privateItem.submenu)
        #expect(sub.items.first { $0.title == "For 15 Minutes" }?.state == .on)
        #expect(menu.items.contains { $0.isSeparatorItem })
        #expect(menu.items.contains { $0.isSectionHeader && $0.title == "Dictation Service" })
    }

    @Test("AC-4: given an open menu, when the countdown ticks, then titles update in place without replacing items")
    func updatesInPlace() throws {
        let menu = NSMenu()
        let first = MenuModel.items(for: state(privateMode: PrivateModeStatus(isActive: true, remainingSeconds: 600, duration: .fifteenMinutes)))
        StatusMenuBuilder.populate(menu, with: first, target: nil, action: nil)
        let headerBefore = menu.items[0]
        let next = MenuModel.items(for: state(privateMode: PrivateModeStatus(isActive: true, remainingSeconds: 599, duration: .fifteenMinutes)))
        StatusMenuBuilder.update(menu, with: next, target: nil, action: nil)
        #expect(menu.items[0] === headerBefore)
        #expect(menu.items[0].title == "Private Mode \u{00B7} 9:59 Left")
        let sub = try #require(menu.items.first { $0.title == "Private Mode" }?.submenu)
        #expect(sub.items.first { $0.title.hasSuffix("Left") }?.title == "9:59 Left")
    }
}
