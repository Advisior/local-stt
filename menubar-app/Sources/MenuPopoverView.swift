import SwiftUI

struct MenuPopoverView: View {
    @ObservedObject var daemon: DaemonManager
    @ObservedObject var config: ConfigManager
    var onSettings: () -> Void
    var onOpenLog: () -> Void
    var onQuit: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            // MARK: - Header
            headerSection

            Divider()
                .padding(.horizontal, 12)

            // MARK: - Actions
            actionsSection

            Divider()
                .padding(.horizontal, 12)

            // MARK: - Tools
            toolsSection

            Divider()
                .padding(.horizontal, 12)

            // MARK: - Footer
            footerSection
        }
        .frame(width: 280)
        .fixedSize(horizontal: true, vertical: true)
    }

    // MARK: - Header

    private var headerSection: some View {
        HStack(spacing: 10) {
            // Status indicator dot
            Circle()
                .fill(daemon.isRunning ? Color.green : Color.red.opacity(0.7))
                .frame(width: 10, height: 10)
                .shadow(color: daemon.isRunning ? .green.opacity(0.5) : .clear, radius: 4)

            VStack(alignment: .leading, spacing: 2) {
                Text("Local-STT")
                    .font(.system(size: 13, weight: .semibold))

                Text(daemon.isRunning
                    ? "Running \u{00B7} \(config.engineLabel)"
                    : "Stopped")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }

            Spacer()

            // Mic icon
            Image(systemName: daemon.isRunning ? "mic.fill" : "mic.slash.fill")
                .font(.system(size: 16))
                .foregroundStyle(daemon.isRunning ? .green : .secondary)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
    }

    // MARK: - Actions

    private var actionsSection: some View {
        VStack(spacing: 2) {
            PopoverMenuItem(
                icon: daemon.isRunning ? "stop.circle" : "play.circle",
                title: daemon.isRunning ? "Stop Daemon" : "Start Daemon",
                tint: daemon.isRunning ? .orange : .green
            ) {
                if daemon.isRunning {
                    daemon.stopDaemon()
                } else {
                    daemon.startDaemon()
                }
            }

            PopoverMenuItem(
                icon: "waveform",
                title: "Toggle Recording",
                shortcut: "\u{2318}R",
                disabled: !daemon.isRunning
            ) {
                daemon.toggleRecording()
            }

            PopoverMenuItem(
                icon: "arrow.clockwise",
                title: "Restart Daemon",
                disabled: !daemon.isRunning
            ) {
                daemon.restartDaemon()
            }
        }
        .padding(.vertical, 6)
    }

    // MARK: - Tools

    private var toolsSection: some View {
        VStack(spacing: 2) {
            PopoverMenuItem(
                icon: "gearshape",
                title: "Settings...",
                shortcut: "\u{2318},"
            ) {
                onSettings()
            }

            PopoverMenuItem(
                icon: "doc.text",
                title: "Open Log"
            ) {
                onOpenLog()
            }
        }
        .padding(.vertical, 6)
    }

    // MARK: - Footer

    private var footerSection: some View {
        HStack {
            Text("v\(AppInfo.version)")
                .font(.system(size: 10))
                .foregroundStyle(.tertiary)

            Spacer()

            Button(action: onQuit) {
                Text("Quit")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)
            .onHover { hovering in
                if hovering {
                    NSCursor.pointingHand.push()
                } else {
                    NSCursor.pop()
                }
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
    }
}

// MARK: - Popover Menu Item

struct PopoverMenuItem: View {
    let icon: String
    let title: String
    var shortcut: String? = nil
    var tint: Color = .primary
    var disabled: Bool = false
    let action: () -> Void

    @State private var isHovered = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Image(systemName: icon)
                    .font(.system(size: 13))
                    .foregroundStyle(disabled ? Color.gray.opacity(0.4) : tint)
                    .frame(width: 20, alignment: .center)

                Text(title)
                    .font(.system(size: 13))
                    .foregroundStyle(disabled ? Color.gray.opacity(0.4) : Color.primary)

                Spacer()

                if let shortcut = shortcut {
                    Text(shortcut)
                        .font(.system(size: 11))
                        .foregroundStyle(.tertiary)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 6)
            .contentShape(Rectangle())
            .background(
                RoundedRectangle(cornerRadius: 6)
                    .fill(isHovered && !disabled
                        ? Color.primary.opacity(0.08)
                        : Color.clear)
                    .padding(.horizontal, 8)
            )
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .onHover { hovering in
            withAnimation(.easeInOut(duration: 0.15)) {
                isHovered = hovering
            }
        }
    }
}
