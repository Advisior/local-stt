import SwiftUI

// MARK: - About Tab

struct AboutTab: View {
    @ObservedObject var daemon: DaemonManager

    private let repoURL = "https://github.com/Advisior/local-stt"
    private let advisiorURL = "https://www.advisior.de"
    private let linkedInURL = "https://www.linkedin.com/in/uwe-franke/"
    private let originalAuthorURL = "https://github.com/jarrodwatts"
    private let semanticAnchorsURL = "https://github.com/LLM-Coding/Semantic-Anchors"

    var body: some View {
        VStack(spacing: 12) {
            Spacer()

            // App icon
            Image(systemName: daemon.isRunning ? "mic.fill" : "mic.slash.fill")
                .font(.system(size: 44))
                .foregroundStyle(daemon.isRunning ? .green : .secondary)

            Text("Local-STT")
                .font(.title2.bold())

            Text("Version \(AppInfo.version)")
                .font(.subheadline)
                .foregroundStyle(.secondary)

            // Status card
            GroupBox {
                VStack(spacing: 10) {
                    aboutRow(
                        icon: "circle.fill",
                        label: "Daemon",
                        value: daemon.isRunning ? "Running" : "Stopped",
                        tint: daemon.isRunning ? .green : .red.opacity(0.7)
                    )
                    Divider()
                    aboutRow(icon: "cpu", label: "Runtime", value: "Apple Silicon (MLX)")
                    Divider()
                    aboutRow(icon: "lock.shield", label: "Privacy", value: "100% local, no cloud")
                    Divider()
                    aboutRow(icon: "doc.text", label: "License", value: "MIT License")
                }
                .padding(4)
            }
            .frame(maxWidth: 320)

            // Links
            VStack(spacing: 6) {
                linkButton(
                    icon: "link",
                    text: "GitHub Repository",
                    url: repoURL
                )

                linkButton(
                    icon: "person.circle",
                    text: "Uwe Franke \u{2014} LinkedIn",
                    url: linkedInURL
                )
            }

            Spacer()

            // Credits
            VStack(spacing: 4) {
                HStack(spacing: 4) {
                    Text("Originally created by")
                        .font(.system(size: 10))
                        .foregroundStyle(.tertiary)
                    creditLink("Jarrod Watts", url: originalAuthorURL)
                }

                HStack(spacing: 4) {
                    creditLink("Semantic Anchors", url: semanticAnchorsURL)
                    Text("by Ralf M\u{00FC}ller")
                        .font(.system(size: 10))
                        .foregroundStyle(.tertiary)
                }

                // Made with love footer
                HStack(spacing: 4) {
                    Text("Maintained with")
                        .font(.system(size: 10))
                        .foregroundStyle(.tertiary)
                    Image(systemName: "heart.fill")
                        .font(.system(size: 9))
                        .foregroundStyle(.red)
                    Text("by")
                        .font(.system(size: 10))
                        .foregroundStyle(.tertiary)

                    Button {
                        if let url = URL(string: advisiorURL) {
                            NSWorkspace.shared.open(url)
                        }
                    } label: {
                        AdvisiorLogoView()
                    }
                    .buttonStyle(.plain)
                    .onHover { hovering in
                        if hovering { NSCursor.pointingHand.push() } else { NSCursor.pop() }
                    }
                }
            }
            .padding(.bottom, 8)
        }
        .frame(maxWidth: .infinity)
    }

    private func aboutRow(
        icon: String,
        label: String,
        value: String,
        tint: Color = .secondary
    ) -> some View {
        HStack {
            Image(systemName: icon)
                .font(.system(size: 10))
                .foregroundStyle(tint)
                .frame(width: 16)
            Text(label)
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
            Spacer()
            Text(value)
                .font(.system(size: 12, weight: .medium))
        }
    }

    private func creditLink(_ text: String, url: String) -> some View {
        Button {
            if let u = URL(string: url) {
                NSWorkspace.shared.open(u)
            }
        } label: {
            Text(text)
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(.blue.opacity(0.7))
        }
        .buttonStyle(.plain)
        .onHover { hovering in
            if hovering { NSCursor.pointingHand.push() } else { NSCursor.pop() }
        }
    }

    private func linkButton(icon: String, text: String, url: String) -> some View {
        Button {
            if let u = URL(string: url) {
                NSWorkspace.shared.open(u)
            }
        } label: {
            HStack(spacing: 5) {
                Image(systemName: icon)
                    .font(.system(size: 11))
                Text(text)
                    .font(.system(size: 12))
            }
            .foregroundStyle(.blue)
        }
        .buttonStyle(.plain)
        .onHover { hovering in
            if hovering { NSCursor.pointingHand.push() } else { NSCursor.pop() }
        }
    }
}

// MARK: - Advisior Logo

private struct AdvisiorLogoView: View {
    var body: some View {
        if let logoImage = loadLogo() {
            Image(nsImage: logoImage)
                .resizable()
                .aspectRatio(contentMode: .fit)
                .frame(height: 14)
        } else {
            Text("Advisior")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(.secondary)
        }
    }

    private func loadLogo() -> NSImage? {
        // 1. Try main bundle resources
        if let bundlePath = Bundle.main.path(forResource: "advisior_logo", ofType: "png") {
            return NSImage(contentsOfFile: bundlePath)
        }

        // 2. Try SPM resource bundle inside main bundle
        let resourcesDir = Bundle.main.bundlePath + "/Contents/Resources"
        if let contents = try? FileManager.default.contentsOfDirectory(atPath: resourcesDir) {
            for item in contents where item.hasSuffix(".bundle") {
                let bundlePath = resourcesDir + "/" + item + "/advisior_logo.png"
                if let img = NSImage(contentsOfFile: bundlePath) {
                    return img
                }
            }
        }

        // 3. Direct file in Resources dir
        let directPath = resourcesDir + "/advisior_logo.png"
        if let img = NSImage(contentsOfFile: directPath) {
            return img
        }

        // 4. Fallback: locate relative to executable
        let execDir = Bundle.main.bundlePath
        let parentDir = (execDir as NSString).deletingLastPathComponent
        let devPath = parentDir + "/menubar-app/Sources/LocalSTTCore/Resources/advisior_logo.png"
        if let img = NSImage(contentsOfFile: devPath) {
            return img
        }

        return nil
    }
}
