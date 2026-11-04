import AppKit
import Testing
@testable import LocalSTTCore

private func freshDefaults() -> UserDefaults {
    let name = "LocalSTTCoreTests.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: name)!
    defaults.removePersistentDomain(forName: name)
    return defaults
}

@Suite @MainActor struct SettingsPaneTests {
    @Test("AC-11: given the settings panes, when listed, then General, Hotkeys, Transcription, Vocabulary and About appear in order with distinct SF Symbols")
    func paneList() {
        #expect(SettingsPane.allCases.map(\.title) == ["General", "Hotkeys", "Transcription", "Vocabulary", "About"])
        #expect(Set(SettingsPane.allCases.map(\.symbol)).count == 5)
        for pane in SettingsPane.allCases {
            #expect(NSImage(systemSymbolName: pane.symbol, accessibilityDescription: nil) != nil)
        }
    }

    @Test("AC-11: given the tab view controller, when created, then it uses a toolbar with one item per pane and the window title follows the pane")
    func tabController() throws {
        let store = SettingsPaneStore(defaults: freshDefaults())
        let tabs = SettingsTabViewController(store: store) { _ in NSViewController() }
        #expect(tabs.tabStyle == .toolbar)
        #expect(tabs.tabViewItems.map(\.label) == SettingsPane.allCases.map(\.title))
        #expect(tabs.tabViewItems.allSatisfy { $0.image != nil })
        tabs.select(.vocabulary)
        #expect(tabs.title == "Vocabulary")
        #expect(tabs.selectedTabViewItemIndex == 3)
    }

    @Test("AC-13: given a pane was last visible, when Settings reopens, then that pane is selected")
    func restoresLastPane() {
        let defaults = freshDefaults()
        let first = SettingsTabViewController(store: SettingsPaneStore(defaults: defaults)) { _ in NSViewController() }
        first.select(.transcription)
        let second = SettingsTabViewController(store: SettingsPaneStore(defaults: defaults)) { _ in NSViewController() }
        #expect(second.selectedTabViewItemIndex == 2)
        #expect(second.title == "Transcription")
    }

    @Test("AC-13: given no or an unknown stored pane, when Settings opens, then General is selected")
    func defaultPane() {
        let defaults = freshDefaults()
        #expect(SettingsPaneStore(defaults: defaults).lastPane == .general)
        defaults.set("privacy-from-the-future", forKey: SettingsPaneStore.key)
        #expect(SettingsPaneStore(defaults: defaults).lastPane == .general)
    }

    @Test("AC-15: given any pane, when sized for a small screen, then the content height never exceeds the available height")
    func heightCapped() {
        for pane in SettingsPane.allCases {
            #expect(pane.contentHeight(maxAvailable: 300) <= 300)
            #expect(pane.contentHeight(maxAvailable: 5000) == pane.idealHeight)
        }
    }
}
