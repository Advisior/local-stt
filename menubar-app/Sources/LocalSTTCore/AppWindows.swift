import AppKit
import SwiftUI

enum WindowPlacement {
    /// The screen under the mouse pointer. window.center() would always pick
    /// the primary display on multi-monitor setups.
    static var activeScreen: NSScreen? {
        let mouse = NSEvent.mouseLocation
        return NSScreen.screens.first { NSMouseInRect(mouse, $0.frame, false) } ?? NSScreen.main
    }

    static func center(_ window: NSWindow) {
        guard let screen = activeScreen else {
            window.center()
            return
        }
        let sf = screen.visibleFrame
        let size = window.frame.size
        window.setFrameOrigin(NSPoint(x: sf.midX - size.width / 2, y: sf.midY - size.height / 2))
    }
}

/// Settings window: toolbar panes, no minimize or zoom (titled and closable only).
enum SettingsWindowFactory {
    static let contentWidth: CGFloat = 520

    static func make(config: ConfigManager, daemon: DaemonManager, onDismiss: @escaping () -> Void) -> NSWindow {
        // Title bar and toolbar take roughly 80 points of the visible frame.
        let maxHeight = (WindowPlacement.activeScreen?.visibleFrame.height ?? 800) - 80
        let tabs = SettingsTabViewController(store: SettingsPaneStore()) { pane in
            let view = SettingsPaneView(
                pane: pane,
                config: config,
                daemon: daemon,
                onDismiss: onDismiss
            )
            .frame(width: contentWidth, height: pane.contentHeight(maxAvailable: maxHeight))
            let host = NSHostingController(rootView: view)
            host.sizingOptions = [.preferredContentSize]
            return host
        }
        let window = NSWindow(contentViewController: tabs)
        window.styleMask = [.titled, .closable]
        window.toolbarStyle = .preference
        window.toolbar?.allowsUserCustomization = false
        window.isReleasedWhenClosed = false
        window.title = tabs.title ?? "Settings"
        return window
    }
}

/// History window with a unified toolbar holding the title and the search field.
final class HistoryWindowController: NSWindowController, NSToolbarDelegate, NSSearchFieldDelegate {
    static let searchItemID = NSToolbarItem.Identifier("history.search")
    let search = HistorySearch()
    private(set) var searchItem: NSSearchToolbarItem?

    init(config: ConfigManager) {
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 560, height: 480),
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        window.title = "History"
        window.isReleasedWhenClosed = false
        super.init(window: window)
        window.contentView = NSHostingView(rootView: HistoryView(config: config, search: search))

        let toolbar = NSToolbar(identifier: "history.toolbar")
        toolbar.delegate = self
        toolbar.displayMode = .iconOnly
        toolbar.allowsUserCustomization = false
        window.toolbar = toolbar
        window.toolbarStyle = .unified
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    // ⌘F (Edit > Find…) reaches this through the responder chain.
    @objc func performFindPanelAction(_ sender: Any?) {
        searchItem?.beginSearchInteraction()
    }

    func toolbarDefaultItemIdentifiers(_ toolbar: NSToolbar) -> [NSToolbarItem.Identifier] {
        [.flexibleSpace, Self.searchItemID]
    }

    func toolbarAllowedItemIdentifiers(_ toolbar: NSToolbar) -> [NSToolbarItem.Identifier] {
        toolbarDefaultItemIdentifiers(toolbar)
    }

    func toolbar(
        _ toolbar: NSToolbar,
        itemForItemIdentifier itemIdentifier: NSToolbarItem.Identifier,
        willBeInsertedIntoToolbar flag: Bool
    ) -> NSToolbarItem? {
        guard itemIdentifier == Self.searchItemID else { return nil }
        let item = NSSearchToolbarItem(itemIdentifier: itemIdentifier)
        item.searchField.placeholderString = "Search"
        item.searchField.delegate = self
        item.searchField.target = self
        item.searchField.action = #selector(searchFieldChanged(_:))
        searchItem = item
        return item
    }

    func controlTextDidChange(_ obj: Notification) {
        guard let field = obj.object as? NSSearchField else { return }
        searchFieldChanged(field)
    }

    // Also fires for the clear button, which does not send a text change.
    @objc private func searchFieldChanged(_ sender: NSSearchField) {
        if search.text != sender.stringValue { search.text = sender.stringValue }
    }
}
