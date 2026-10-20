import AppKit

/// Main menu for the accessory app. It is never shown in the menu bar, but
/// its key equivalents make ⌘, ⌘W ⌘Q and the Edit shortcuts work in windows.
enum MainMenu {
    static func build(target: AnyObject, settings: Selector, quit: Selector) -> NSMenu {
        let main = NSMenu()

        let app = NSMenu(title: "Local-STT")
        let settingsItem = app.addItem(withTitle: "Settings\u{2026}", action: settings, keyEquivalent: ",")
        settingsItem.target = target
        app.addItem(.separator())
        let quitItem = app.addItem(withTitle: "Quit Local-STT", action: quit, keyEquivalent: "q")
        quitItem.target = target
        add(app, to: main)

        let file = NSMenu(title: "File")
        file.addItem(withTitle: "Close Window", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        add(file, to: main)

        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = edit.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        edit.addItem(.separator())
        // Tag 1 is NSFindPanelAction.showFindPanel; the History window maps it
        // to its toolbar search field.
        let find = edit.addItem(withTitle: "Find\u{2026}", action: #selector(NSTextView.performFindPanelAction(_:)), keyEquivalent: "f")
        find.tag = Int(NSFindPanelAction.showFindPanel.rawValue)
        add(edit, to: main)

        return main
    }

    private static func add(_ submenu: NSMenu, to main: NSMenu) {
        let item = NSMenuItem(title: submenu.title, action: nil, keyEquivalent: "")
        item.submenu = submenu
        main.addItem(item)
    }
}
