import ServiceManagement
import SwiftUI

/// One Settings pane plus the shared Save/Cancel bar. All panes edit the same
/// `ConfigManager`, so switching panes keeps unsaved edits.
struct SettingsPaneView: View {
    let pane: SettingsPane
    @ObservedObject var config: ConfigManager
    @ObservedObject var daemon: DaemonManager
    var onDismiss: () -> Void

    @State private var showRestartAlert = false

    var body: some View {
        VStack(spacing: 0) {
            content

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

    @ViewBuilder private var content: some View {
        switch pane {
        case .general: GeneralTab(config: config)
        case .hotkeys: HotkeysTab(config: config)
        case .transcription: TranscriptionTab(config: config)
        case .vocabulary: VocabularyTab(config: config)
        case .about: AboutTab(daemon: daemon)
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
                    .onChange(of: launchAtLogin) { _, newValue in
                        setLaunchAtLogin(newValue)
                    }
            } header: {
                Label("Startup", systemImage: "power")
            }

            Section {
                Toggle("Sound Effects", isOn: $config.soundEffects)

                Toggle("Mute system audio while recording", isOn: $config.muteOnRecord)
                    .onChange(of: config.muteOnRecord) { config.save() }

                VStack(alignment: .leading, spacing: 4) {
                    LabeledContent("Engine") {
                        Picker("", selection: $config.engine) {
                            Text("MLX Whisper").tag("mlx")
                            Text("Parakeet TDT").tag("parakeet")
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
                        Picker("", selection: modelBinding) {
                            if config.engine == "moonshine" {
                                Text("Tiny").tag("moonshine/tiny")
                                Text("Base").tag("moonshine/base")
                            } else if config.engine == "parakeet" {
                                Text("TDT 0.6B v3").tag("tdt-0.6b-v3")
                                Text("TDT 0.6B v2").tag("tdt-0.6b-v2")
                                Text("TDT 1.1B").tag("tdt-1.1b")
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

    private var modelBinding: Binding<String> {
        switch config.engine {
        case "moonshine": return $config.moonshineModel
        case "parakeet": return $config.parakeetModel
        default: return $config.whisperModel
        }
    }
}

// MARK: - Hotkeys Tab

private struct HotkeysTab: View {
    @ObservedObject var config: ConfigManager

    var body: some View {
        Form {
            Section {
                VStack(alignment: .leading, spacing: 4) {
                    LabeledContent("Hotkey") {
                        HotkeyRecorderView(hotkeyString: $config.hotkey)
                    }
                    settingHint("Click the field and press your desired key or combination")
                }

                VStack(alignment: .leading, spacing: 4) {
                    LabeledContent("Undo last dictation") {
                        HotkeyRecorderView(hotkeyString: $config.undoHotkey)
                    }
                    settingHint("Optional. Removes the last dictation with Backspaces, until you type or switch apps")
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
        }
        .formStyle(.grouped)
    }
}

// MARK: - Transcription Tab

private struct TranscriptionTab: View {
    @ObservedObject var config: ConfigManager

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

        }
        .formStyle(.grouped)
    }
}

// MARK: - Vocabulary Tab

private struct VocabularyTab: View {
    @ObservedObject var config: ConfigManager

    private let maxVocabularyChars = 1000

    private var charsUsed: Int { config.initialPrompt.count }
    private var isOverLimit: Bool { charsUsed > maxVocabularyChars }

    var body: some View {
        Form {
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

// MARK: - Shared Helpers

private func settingHint(_ text: String) -> some View {
    Text(text)
        .font(.system(size: 11))
        .foregroundStyle(.tertiary)
        .fixedSize(horizontal: false, vertical: true)
}
