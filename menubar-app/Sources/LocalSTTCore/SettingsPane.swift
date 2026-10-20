import AppKit

/// Panes of the Settings window, in toolbar order.
enum SettingsPane: String, CaseIterable {
    case general, hotkeys, transcription, vocabulary, about

    var title: String {
        switch self {
        case .general: return "General"
        case .hotkeys: return "Hotkeys"
        case .transcription: return "Transcription"
        case .vocabulary: return "Vocabulary"
        case .about: return "About"
        }
    }

    var symbol: String {
        switch self {
        case .general: return "gearshape"
        case .hotkeys: return "keyboard"
        case .transcription: return "text.bubble"
        case .vocabulary: return "textformat.abc"
        case .about: return "info.circle"
        }
    }

    /// Content height including the Save/Cancel bar, before capping to the screen.
    var idealHeight: CGFloat {
        switch self {
        case .general: return 500
        case .hotkeys: return 330
        case .transcription: return 190
        case .vocabulary: return 420
        case .about: return 520
        }
    }

    /// Never taller than the space left on screen; the grouped forms scroll instead.
    func contentHeight(maxAvailable: CGFloat) -> CGFloat {
        min(idealHeight, max(0, maxAvailable))
    }
}

/// Remembers the last visible Settings pane in `UserDefaults`.
struct SettingsPaneStore {
    static let key = "settingsLastPane"
    let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    var lastPane: SettingsPane {
        defaults.string(forKey: Self.key).flatMap(SettingsPane.init(rawValue:)) ?? .general
    }

    func save(_ pane: SettingsPane) {
        defaults.set(pane.rawValue, forKey: Self.key)
    }
}

/// Toolbar pane switcher. The window title follows the selected pane and the
/// selection is persisted, as the HIG asks for settings windows.
final class SettingsTabViewController: NSTabViewController {
    private let store: SettingsPaneStore

    init(store: SettingsPaneStore, makeContent: (SettingsPane) -> NSViewController) {
        self.store = store
        super.init(nibName: nil, bundle: nil)
        tabStyle = .toolbar
        canPropagateSelectedChildViewControllerTitle = false
        for pane in SettingsPane.allCases {
            let controller = makeContent(pane)
            controller.title = pane.title
            let item = NSTabViewItem(viewController: controller)
            item.label = pane.title
            item.identifier = pane.rawValue
            item.image = NSImage(systemSymbolName: pane.symbol, accessibilityDescription: pane.title)
            addTabViewItem(item)
        }
        let initial = store.lastPane
        selectedTabViewItemIndex = SettingsPane.allCases.firstIndex(of: initial) ?? 0
        title = initial.title
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError("init(coder:) is not supported") }

    func select(_ pane: SettingsPane) {
        selectedTabViewItemIndex = SettingsPane.allCases.firstIndex(of: pane) ?? 0
        didShow(pane)
    }

    // Toolbar clicks arrive here once the view is loaded.
    override func tabView(_ tabView: NSTabView, didSelect tabViewItem: NSTabViewItem?) {
        super.tabView(tabView, didSelect: tabViewItem)
        guard let raw = tabViewItem?.identifier as? String, let pane = SettingsPane(rawValue: raw) else { return }
        didShow(pane)
    }

    private func didShow(_ pane: SettingsPane) {
        title = pane.title
        if isViewLoaded { view.window?.title = pane.title }
        store.save(pane)
    }
}
