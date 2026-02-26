import AppKit
import Combine
import SwiftUI

class MenuBarController: NSObject {
    private var statusItem: NSStatusItem!
    private let daemon = DaemonManager()
    private let config = ConfigManager()
    private var cancellables = Set<AnyCancellable>()
    private var settingsWindow: NSWindow?
    private var popover: NSPopover!
    private var eventMonitor: Any?

    override init() {
        super.init()
        setupStatusItem()
        setupPopover()

        daemon.$isRunning
            .receive(on: DispatchQueue.main)
            .sink { [weak self] running in
                self?.applyIcon(running: running)
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

    // MARK: - Setup

    private func setupStatusItem() {
        statusItem = NSStatusBar.system.statusItem(
            withLength: NSStatusItem.variableLength
        )
        applyIcon(running: false)

        if let button = statusItem.button {
            button.action = #selector(onStatusItemClicked)
            button.target = self
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }
    }

    private func setupPopover() {
        popover = NSPopover()
        popover.behavior = .transient
        popover.animates = true

        let popoverView = MenuPopoverView(
            daemon: daemon,
            config: config,
            onSettings: { [weak self] in
                self?.closePopover()
                self?.onOpenSettings()
            },
            onOpenLog: { [weak self] in
                self?.closePopover()
                self?.onOpenLog()
            },
            onQuit: { [weak self] in
                self?.closePopover()
                self?.onQuit()
            }
        )

        popover.contentViewController = NSHostingController(rootView: popoverView)
    }

    private func applyIcon(running: Bool) {
        let symbolName = running ? "mic.fill" : "mic.slash.fill"
        if let image = NSImage(
            systemSymbolName: symbolName,
            accessibilityDescription: "Local-STT"
        ) {
            image.isTemplate = true
            statusItem.button?.image = image
        }
    }

    // MARK: - Popover

    @objc private func onStatusItemClicked() {
        guard let button = statusItem.button else { return }

        if popover.isShown {
            closePopover()
        } else {
            config.load()
            popover.show(
                relativeTo: button.bounds,
                of: button,
                preferredEdge: .minY
            )
            startEventMonitor()
        }
    }

    private func closePopover() {
        popover.performClose(nil)
        stopEventMonitor()
    }

    private func startEventMonitor() {
        eventMonitor = NSEvent.addGlobalMonitorForEvents(
            matching: [.leftMouseDown, .rightMouseDown]
        ) { [weak self] _ in
            if let self = self, self.popover.isShown {
                self.closePopover()
            }
        }
    }

    private func stopEventMonitor() {
        if let monitor = eventMonitor {
            NSEvent.removeMonitor(monitor)
            eventMonitor = nil
        }
    }

    // MARK: - Actions

    private func onOpenSettings() {
        if let window = settingsWindow, window.isVisible {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }

        // Clean up any non-visible stale window reference
        settingsWindow?.close()
        settingsWindow = nil

        config.load()

        let settingsView = SettingsView(
            config: config,
            daemon: daemon,
            onDismiss: { [weak self] in
                self?.settingsWindow?.close()
            }
        )

        let hostingView = NSHostingView(rootView: settingsView)
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 520, height: 540),
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        window.title = "Local-STT Settings"
        window.contentView = hostingView
        window.isReleasedWhenClosed = false

        // Center on the screen containing the mouse cursor, not the system
        // main screen. On multi-monitor setups window.center() always places
        // the window on the primary display, which may not be the active one.
        let mouseLocation = NSEvent.mouseLocation
        let activeScreen = NSScreen.screens.first { screen in
            NSMouseInRect(mouseLocation, screen.frame, false)
        } ?? NSScreen.main
        if let screen = activeScreen {
            let sf = screen.visibleFrame
            let origin = NSPoint(x: sf.midX - 260, y: sf.midY - 270)
            window.setFrameOrigin(origin)
        } else {
            window.center()
        }

        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        settingsWindow = window
    }

    private func onOpenLog() {
        let logFile = URL(fileURLWithPath: "/tmp/claude-stt.log")
        if FileManager.default.fileExists(atPath: logFile.path) {
            NSWorkspace.shared.open(logFile)
        }
    }

    private func onQuit() {
        if daemon.isRunning {
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
