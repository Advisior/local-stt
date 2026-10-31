import AppKit

public final class AppDelegate: NSObject, NSApplicationDelegate {
    private var menuBar: MenuBarController!

    override public init() { super.init() }

    public func applicationDidFinishLaunching(_ notification: Notification) {
        menuBar = MenuBarController()
        NSApp.mainMenu = MainMenu.build(
            target: menuBar,
            settings: #selector(MenuBarController.openSettings(_:)),
            quit: #selector(MenuBarController.quit(_:))
        )
    }

    /// Launching the app again (Finder, Spotlight, `open -a`) opens Settings,
    /// so the app stays reachable when the menu bar hides its icon.
    public func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        menuBar.openSettings()
        return true
    }
}
