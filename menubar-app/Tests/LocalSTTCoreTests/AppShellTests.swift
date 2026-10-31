import AppKit
import Testing
@testable import LocalSTTCore

private func entry(_ line: Int, _ text: String) -> HistoryEntry {
    HistoryEntry(line: line, timestamp: "2026-10-20T10:00:0\(line)", text: text, durationS: 1, db: -20)
}

@Suite struct HistoryFilterTests {
    let entries = [entry(0, "Hello World"), entry(1, "Grüße aus Köln"), entry(2, "kubernetes cluster")]

    @Test("AC-17: given a query, when filtering, then entries match case-insensitive substrings")
    func caseInsensitive() {
        #expect(HistoryFilter.filter(entries, query: "world").map(\.line) == [0])
        #expect(HistoryFilter.filter(entries, query: "KÖLN").map(\.line) == [1])
        #expect(HistoryFilter.filter(entries, query: "e").map(\.line) == [0, 1, 2])
    }

    @Test("AC-17: given an empty query, when filtering, then all entries are returned; given no match, then none")
    func emptyAndNoMatch() {
        #expect(HistoryFilter.filter(entries, query: "").count == 3)
        #expect(HistoryFilter.filter(entries, query: "zzz").isEmpty)
        #expect(HistoryFilter.filter([], query: "a").isEmpty)
    }
}

@Suite @MainActor struct MainMenuTests {
    private final class Target: NSObject {
        @objc func openSettings(_ sender: Any?) {}
        @objc func quit(_ sender: Any?) {}
    }

    private func find(_ menu: NSMenu, _ title: String) -> NSMenuItem? {
        for item in menu.items {
            if item.title == title { return item }
            if let sub = item.submenu, let found = find(sub, title) { return found }
        }
        return nil
    }

    @Test("AC-19: given the main menu, when built, then Settings, Close Window and Quit carry their key equivalents")
    func appItems() throws {
        let target = Target()
        let menu = MainMenu.build(target: target, settings: #selector(Target.openSettings(_:)), quit: #selector(Target.quit(_:)))
        let settings = try #require(find(menu, "Settings\u{2026}"))
        #expect(settings.keyEquivalent == "," && settings.keyEquivalentModifierMask == .command)
        #expect(settings.action == #selector(Target.openSettings(_:)))
        #expect(settings.target === target)
        let close = try #require(find(menu, "Close Window"))
        #expect(close.keyEquivalent == "w" && close.action == #selector(NSWindow.performClose(_:)))
        let quit = try #require(find(menu, "Quit Local-STT"))
        #expect(quit.keyEquivalent == "q" && quit.action == #selector(Target.quit(_:)))
    }

    @Test("AC-19: given the main menu, when built, then the Edit menu sends the standard responder actions")
    func editMenu() throws {
        let menu = MainMenu.build(target: Target(), settings: #selector(Target.openSettings(_:)), quit: #selector(Target.quit(_:)))
        let edit = try #require(menu.items.first { $0.title == "Edit" }?.submenu)
        let pairs = edit.items.filter { !$0.isSeparatorItem }.map { ($0.keyEquivalent, $0.keyEquivalentModifierMask, $0.action) }
        func has(_ key: String, _ mods: NSEvent.ModifierFlags, _ sel: Selector) -> Bool {
            pairs.contains { $0.0 == key && $0.1 == mods && $0.2 == sel }
        }
        #expect(has("z", .command, Selector(("undo:"))))
        #expect(has("z", [.command, .shift], Selector(("redo:"))))
        #expect(has("x", .command, #selector(NSText.cut(_:))))
        #expect(has("c", .command, #selector(NSText.copy(_:))))
        #expect(has("v", .command, #selector(NSText.paste(_:))))
        #expect(has("a", .command, #selector(NSText.selectAll(_:))))
        #expect(has("f", .command, #selector(NSTextView.performFindPanelAction(_:))))
    }
}
