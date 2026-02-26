import ServiceManagement
import SwiftUI

struct SettingsView: View {
    @ObservedObject var config: ConfigManager
    @ObservedObject var daemon: DaemonManager
    var onDismiss: () -> Void

    @State private var showRestartAlert = false

    var body: some View {
        VStack(spacing: 0) {
            TabView {
                GeneralTab(config: config)
                    .tabItem {
                        Label("General", systemImage: "gearshape")
                    }

                TranscriptionTab(config: config)
                    .tabItem {
                        Label("Transcription", systemImage: "text.bubble")
                    }

                AboutTab(daemon: daemon)
                    .tabItem {
                        Label("About", systemImage: "info.circle")
                    }
            }

            Divider()

            HStack {
                Spacer()
                Button("Cancel") {
                    config.load()
                    onDismiss()
                }
                .keyboardShortcut(.cancelAction)

                Button("Save") {
                    config.save()
                    if daemon.isRunning {
                        showRestartAlert = true
                    } else {
                        onDismiss()
                    }
                }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
                .tint(.accentColor)
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 12)
        }
        .frame(width: 520, height: 540)
        .alert("Restart Daemon?", isPresented: $showRestartAlert) {
            Button("Restart Now") {
                daemon.restartDaemon()
                onDismiss()
            }
            Button("Later") {
                onDismiss()
            }
        } message: {
            Text("Settings saved. Restart the daemon to apply changes?")
        }
    }
}

// MARK: - General Tab

private struct GeneralTab: View {
    @ObservedObject var config: ConfigManager
    @State private var launchAtLogin: Bool = false

    var body: some View {
        Form {
            Section {
                Toggle("Start daemon when app opens", isOn: $config.autoStartDaemon)

                Toggle("Launch at Login", isOn: $launchAtLogin)
                    .onChange(of: launchAtLogin) { newValue in
                        setLaunchAtLogin(newValue)
                    }
            } header: {
                Label("Startup", systemImage: "power")
            }

            Section {
                VStack(alignment: .leading, spacing: 4) {
                    LabeledContent("Hotkey") {
                        HotkeyRecorderView(hotkeyString: $config.hotkey)
                    }
                    settingHint("Click the field and press your desired key or combination")
                }

                VStack(alignment: .leading, spacing: 4) {
                    LabeledContent("Mode") {
                        Picker("", selection: $config.mode) {
                            Text("Push-to-Talk").tag("push-to-talk")
                            Text("Toggle").tag("toggle")
                        }
                        .pickerStyle(.segmented)
                        .labelsHidden()
                        .frame(width: 200)
                    }
                    settingHint("Push-to-Talk: hold key to record. Toggle: press to start/stop")
                }
            } header: {
                Label("Input", systemImage: "keyboard")
            }

            Section {
                Toggle("Sound Effects", isOn: $config.soundEffects)

                Toggle("Mute system audio while recording", isOn: $config.muteOnRecord)
                    .onChange(of: config.muteOnRecord) { _ in config.save() }

                VStack(alignment: .leading, spacing: 4) {
                    LabeledContent("Engine") {
                        Picker("", selection: $config.engine) {
                            Text("MLX Whisper").tag("mlx")
                            Text("Whisper").tag("whisper")
                            Text("Moonshine").tag("moonshine")
                        }
                        .labelsHidden()
                        .frame(width: 180)
                    }
                    if isAppleSilicon {
                        settingHint("MLX Whisper recommended \u{2014} optimized for Apple Silicon, fastest on M-series chips")
                    } else {
                        settingHint("Whisper recommended for Intel Macs. MLX requires Apple Silicon")
                    }
                }

                VStack(alignment: .leading, spacing: 4) {
                    LabeledContent("Model") {
                        Picker("", selection: config.engine == "moonshine"
                            ? $config.moonshineModel
                            : $config.whisperModel
                        ) {
                            if config.engine == "moonshine" {
                                Text("Tiny").tag("moonshine/tiny")
                                Text("Base").tag("moonshine/base")
                            } else {
                                Text("Tiny").tag("tiny")
                                Text("Base").tag("base")
                                Text("Small").tag("small")
                                Text("Medium").tag("medium")
                                Text("Large").tag("large")
                                Text("Large v3").tag("large-v3")
                                Text("Large v3 Turbo").tag("large-v3-turbo")
                            }
                        }
                        .labelsHidden()
                        .frame(width: 180)
                    }
                    settingHint("Larger models are more accurate but slower. Medium is a good balance")
                }

                if config.engine == "moonshine" {
                    HStack(spacing: 4) {
                        Image(systemName: "info.circle")
                            .font(.system(size: 10))
                            .foregroundStyle(.orange)
                        Text("Moonshine does not support language or vocabulary settings")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                }
            } header: {
                Label("Audio", systemImage: "speaker.wave.2")
            }
        }
        .formStyle(.grouped)
        .onAppear {
            launchAtLogin = SMAppService.mainApp.status == .enabled
        }
    }

    private func setLaunchAtLogin(_ enabled: Bool) {
        do {
            if enabled {
                try SMAppService.mainApp.register()
            } else {
                try SMAppService.mainApp.unregister()
            }
        } catch {
            NSLog("Local-STT: Failed to set launch at login: %@", error.localizedDescription)
            // Revert toggle to actual state
            launchAtLogin = SMAppService.mainApp.status == .enabled
        }
    }

    private var isAppleSilicon: Bool {
        var sysinfo = utsname()
        uname(&sysinfo)
        let machine = withUnsafePointer(to: &sysinfo.machine) {
            $0.withMemoryRebound(to: CChar.self, capacity: 1) {
                String(validatingUTF8: $0)
            }
        }
        return machine?.contains("arm64") == true
    }
}

// MARK: - Transcription Tab

private struct TranscriptionTab: View {
    @ObservedObject var config: ConfigManager

    private let maxVocabularyChars = 1000

    private var charsUsed: Int { config.initialPrompt.count }
    private var charsRemaining: Int { max(0, maxVocabularyChars - charsUsed) }
    private var isOverLimit: Bool { charsUsed > maxVocabularyChars }

    var body: some View {
        Form {
            Section {
                VStack(alignment: .leading, spacing: 4) {
                    LabeledContent("Language") {
                        Picker("", selection: $config.language) {
                            Text("\u{1F310} Auto-detect").tag("")
                            Divider()
                            Text("\u{1F1E9}\u{1F1EA} Deutsch").tag("de")
                            Text("\u{1F1EC}\u{1F1E7} English").tag("en")
                            Text("\u{1F1EB}\u{1F1F7} Fran\u{00E7}ais").tag("fr")
                            Text("\u{1F1EA}\u{1F1F8} Espa\u{00F1}ol").tag("es")
                            Text("\u{1F1EE}\u{1F1F9} Italiano").tag("it")
                            Text("\u{1F1F5}\u{1F1F9} Portugu\u{00EA}s").tag("pt")
                            Text("\u{1F1F3}\u{1F1F1} Nederlands").tag("nl")
                            Text("\u{1F1F5}\u{1F1F1} Polski").tag("pl")
                            Text("\u{1F1F9}\u{1F1F7} T\u{00FC}rk\u{00E7}e").tag("tr")
                            Text("\u{1F1EF}\u{1F1F5} \u{65E5}\u{672C}\u{8A9E}").tag("ja")
                            Text("\u{1F1E8}\u{1F1F3} \u{4E2D}\u{6587}").tag("zh")
                            Text("\u{1F1F0}\u{1F1F7} \u{D55C}\u{AD6D}\u{C5B4}").tag("ko")
                            Text("\u{1F1F7}\u{1F1FA} \u{0420}\u{0443}\u{0441}\u{0441}\u{043A}\u{0438}\u{0439}").tag("ru")
                            Text("\u{1F1F8}\u{1F1E6} \u{0627}\u{0644}\u{0639}\u{0631}\u{0628}\u{064A}\u{0629}").tag("ar")
                        }
                        .labelsHidden()
                        .frame(width: 200)
                    }
                    settingHint("Speech recognition language \u{2014} determines which language the engine listens for, not the app interface")
                }
            } header: {
                Label("Recognition", systemImage: "globe")
            }

            Section {
                VStack(alignment: .leading, spacing: 8) {
                    TextEditor(text: $config.initialPrompt)
                        .font(.system(.body, design: .monospaced))
                        .frame(minHeight: 180, maxHeight: 240)
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                        .overlay(
                            RoundedRectangle(cornerRadius: 6)
                                .stroke(
                                    isOverLimit ? Color.red.opacity(0.6) : Color.gray.opacity(0.3),
                                    lineWidth: 1
                                )
                        )

                    HStack {
                        Text("Comma-separated terms to improve recognition accuracy")
                            .font(.caption)
                            .foregroundStyle(.secondary)

                        Spacer()

                        Text("\(charsUsed) / \(maxVocabularyChars)")
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundStyle(isOverLimit ? .red : .secondary)
                    }

                    settingHint("Add domain-specific terms the engine might not recognize correctly, e.g. TypeScript, Kubernetes, PostgreSQL, GraphQL, Terraform, CI/CD, OAuth, WebSocket")
                }
            } header: {
                Label("Vocabulary", systemImage: "textformat.abc")
            }
        }
        .formStyle(.grouped)
    }
}

// MARK: - About Tab

private struct AboutTab: View {
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
        let devPath = parentDir + "/menubar-app/Sources/Resources/advisior_logo.png"
        if let img = NSImage(contentsOfFile: devPath) {
            return img
        }

        return nil
    }
}

// MARK: - Shared Helpers

private func settingHint(_ text: String) -> some View {
    Text(text)
        .font(.system(size: 11))
        .foregroundStyle(.tertiary)
        .fixedSize(horizontal: false, vertical: true)
}
