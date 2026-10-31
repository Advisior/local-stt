import AppKit
import Combine
import SwiftUI

final class MenuBarController: NSObject, NSMenuDelegate {
    private var statusItem: NSStatusItem!
    private let statusMenu = NSMenu()
    private let daemon = DaemonManager()
    private let config = ConfigManager()
    private let privateMode = PrivateModeManager()
    private var cancellables = Set<AnyCancellable>()
    private var settingsWindow: NSWindow?
    private var historyController: HistoryWindowController?
    private var menuTimer: Timer?

    override init() {
        super.init()
        setupStatusItem()

        daemon.$isRunning
            .combineLatest(privateMode.$isActive)
            .receive(on: DispatchQueue.main)
            .sink { [weak self] running, isPrivate in
                self?.applyIcon(running: running, isPrivate: isPrivate)
            }
            .store(in: &cancellables)

        // Auto-start daemon if enabled in config (no permission prompts)
        if config.autoStartDaemon && !daemon.isRunning {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in
                guard let self = self, !self.daemon.isRunning else { return }
                self.daemon.startDaemon(promptForPermissions: false)
            }
        }
    }

    // MARK: - Status item

    private func setupStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        applyIcon(running: false, isPrivate: privateMode.isActive)
        // With a menu attached, left and right click both open it, and AppKit
        // handles arrow keys, type-select and Esc.
        statusMenu.delegate = self
        statusItem.menu = statusMenu
    }

    private func applyIcon(running: Bool, isPrivate: Bool) {
        // Private mode gets its own glyph so it is visible at a glance.
        let symbolName = isPrivate ? "eye.slash.fill" : running ? "mic.fill" : "mic.slash.fill"
        if let image = NSImage(
            systemSymbolName: symbolName,
            accessibilityDescription: isPrivate ? "Local-STT (private mode)" : "Local-STT"
        ) {
            image.isTemplate = true
            statusItem.button?.image = image
        }
    }

    // MARK: - Menu

    private var menuState: MenuState {
        MenuState(
            service: daemon.isStarting ? .starting : daemon.isRunning ? .running : .stopped,
            permissionsReady: daemon.permissionsReady,
            privateMode: privateMode.status,
            engineSummary: config.serviceSummary,
            hotkeyLabel: config.hotkeyLabel
        )
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        guard menu === statusMenu else { return }
        config.load()
        StatusMenuBuilder.populate(statusMenu, with: MenuModel.items(for: menuState),
                                   target: self, action: #selector(performMenuAction(_:)))
    }

    func menuWillOpen(_ menu: NSMenu) {
        guard menu === statusMenu, menuTimer == nil else { return }
        // Common mode keeps the countdown running while the menu tracks.
        let timer = Timer(timeInterval: 1, repeats: true) { [weak self] _ in self?.refreshOpenMenu() }
        RunLoop.main.add(timer, forMode: .common)
        menuTimer = timer
    }

    func menuDidClose(_ menu: NSMenu) {
        guard menu === statusMenu else { return }
        menuTimer?.invalidate()
        menuTimer = nil
    }

    private func refreshOpenMenu() {
        StatusMenuBuilder.update(statusMenu, with: MenuModel.items(for: menuState),
                                 target: self, action: #selector(performMenuAction(_:)))
    }

    @objc private func performMenuAction(_ sender: NSMenuItem) {
        guard let box = sender.representedObject as? StatusMenuBuilder.ActionBox else { return }
        switch box.action {
        case .toggleRecording: daemon.toggleRecording()
        case .enablePrivateMode(let duration): privateMode.enable(duration)
        case .disablePrivateMode: privateMode.disable()
        case .openHistory: openHistory()
        case .openSettings: openSettings()
        case .startService: daemon.startDaemon()
        case .restartService: daemon.restartDaemon()
        case .stopService: daemon.stopDaemon()
        case .openLog: openLog()
        case .openPermissions: openPermissionSettings()
        case .quit: quit()
        }
    }

    // MARK: - Actions

    @objc func openSettings(_ sender: Any? = nil) {
        if let window = settingsWindow, window.isVisible {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate()
            return
        }
        // Clean up any non-visible stale window reference
        settingsWindow?.close()
        settingsWindow = nil

        config.load()
        let window = SettingsWindowFactory.make(config: config, daemon: daemon) { [weak self] in
            self?.settingsWindow?.close()
        }
        WindowPlacement.center(window)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate()
        settingsWindow = window
    }

    private func openHistory() {
        if let window = historyController?.window, window.isVisible {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate()
            return
        }
        historyController?.close()
        let controller = HistoryWindowController(config: config)
        if let window = controller.window { WindowPlacement.center(window) }
        controller.showWindow(nil)
        NSApp.activate()
        historyController = controller
    }

    private func openLog() {
        let logFile = ConfigManager.configDir.appendingPathComponent("daemon.log")
        if FileManager.default.fileExists(atPath: logFile.path) {
            NSWorkspace.shared.open(logFile)
        }
    }

    private func openPermissionSettings() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy") {
            NSWorkspace.shared.open(url)
        }
    }

    @objc func quit(_ sender: Any? = nil) {
        if daemon.isRunning {
            // An accessory app is not active after a menu click; without this
            // the alert would open behind the frontmost app.
            NSApp.activate()
            let alert = NSAlert()
            alert.messageText = "Quit Local-STT"
            alert.informativeText = "The STT daemon is still running. Stop it before quitting?"
            alert.addButton(withTitle: "Stop & Quit")
            alert.addButton(withTitle: "Quit (keep running)")
            alert.addButton(withTitle: "Cancel")

            let response = alert.runModal()
            switch response {
            case .alertFirstButtonReturn:
                daemon.stopDaemon()
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
                    NSApp.terminate(nil)
                }
                return
            case .alertSecondButtonReturn:
                break
            default:
                return
            }
        }
        NSApp.terminate(nil)
    }
}
