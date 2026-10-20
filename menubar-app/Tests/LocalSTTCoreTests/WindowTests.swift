import AppKit
import Testing
@testable import LocalSTTCore

@Suite @MainActor struct WindowTests {
    @Test("AC-11, AC-15: given the Settings window, when created, then it has a fixed toolbar, the pane title and no minimize or zoom")
    func settingsWindow() throws {
        let window = SettingsWindowFactory.make(
            config: ConfigManager(loadFromDisk: false), daemon: DaemonManager(), onDismiss: {}
        )
        #expect(window.styleMask.contains(.titled))
        #expect(window.styleMask.contains(.closable))
        #expect(!window.styleMask.contains(.miniaturizable))
        #expect(!window.styleMask.contains(.resizable))
        let toolbar = try #require(window.toolbar)
        #expect(toolbar.allowsUserCustomization == false)
        #expect(SettingsPane.allCases.map(\.title).contains(window.title))
    }

    @Test("AC-16: given the History window, when created, then it has a unified toolbar titled History with a search field")
    func historyWindow() throws {
        let controller = HistoryWindowController(config: ConfigManager(loadFromDisk: false))
        let window = try #require(controller.window)
        #expect(window.title == "History")
        #expect(window.toolbarStyle == .unified)
        let toolbar = try #require(window.toolbar)
        #expect(toolbar.items.contains { $0 is NSSearchToolbarItem })
        #expect(controller.responds(to: #selector(NSTextView.performFindPanelAction(_:))))
    }

    @Test("AC-17: given the History toolbar search, when the user types or clears, then the shared search text follows")
    func searchBinding() throws {
        let controller = HistoryWindowController(config: ConfigManager(loadFromDisk: false))
        _ = controller.window?.toolbar?.items
        let field = try #require(controller.searchItem?.searchField)
        field.stringValue = "kube"
        controller.controlTextDidChange(Notification(name: NSControl.textDidChangeNotification, object: field))
        #expect(controller.search.text == "kube")
        field.stringValue = ""
        _ = field.sendAction(field.action, to: field.target)
        #expect(controller.search.text == "")
    }
}
