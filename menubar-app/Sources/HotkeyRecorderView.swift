import SwiftUI
import AppKit
import Carbon.HIToolbox

// MARK: - Hotkey Recorder SwiftUI Wrapper

struct HotkeyRecorderView: View {
    @Binding var hotkeyString: String
    @State private var isRecording = false
    @State private var displayText = ""
    @State private var conflict: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                HotkeyField(
                    hotkeyString: $hotkeyString,
                    isRecording: $isRecording,
                    displayText: $displayText,
                    conflict: $conflict
                )
                .frame(width: 180, height: 28)

                if isRecording {
                    Text("Press a key...")
                        .font(.system(size: 11))
                        .foregroundStyle(.orange)
                } else if !hotkeyString.isEmpty {
                    Button {
                        hotkeyString = ""
                        displayText = ""
                        conflict = nil
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)
                }
            }

            if let conflict = conflict {
                HStack(spacing: 4) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .font(.system(size: 10))
                        .foregroundStyle(.orange)
                    Text(conflict)
                        .font(.system(size: 11))
                        .foregroundStyle(.orange)
                }
            }
        }
        .onAppear {
            displayText = humanReadable(hotkeyString)
            conflict = checkConflict(hotkeyString)
        }
        .onChange(of: hotkeyString) { newValue in
            displayText = humanReadable(newValue)
            conflict = checkConflict(newValue)
        }
    }
}

// MARK: - NSViewRepresentable Key Capture Field

struct HotkeyField: NSViewRepresentable {
    @Binding var hotkeyString: String
    @Binding var isRecording: Bool
    @Binding var displayText: String
    @Binding var conflict: String?

    func makeNSView(context: Context) -> HotkeyNSTextField {
        let field = HotkeyNSTextField()
        field.delegate = context.coordinator
        field.coordinator = context.coordinator
        field.stringValue = displayText
        field.isEditable = false
        field.isSelectable = false
        field.alignment = .center
        field.font = .systemFont(ofSize: 12, weight: .medium)
        field.isBordered = true
        field.isBezeled = true
        field.bezelStyle = .roundedBezel
        field.backgroundColor = .controlBackgroundColor
        field.focusRingType = .none
        return field
    }

    func updateNSView(_ nsView: HotkeyNSTextField, context: Context) {
        nsView.stringValue = isRecording ? "Recording..." : displayText
        nsView.textColor = isRecording ? .systemOrange : .labelColor
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(parent: self)
    }

    class Coordinator: NSObject, NSTextFieldDelegate {
        let parent: HotkeyField
        var localMonitor: Any?

        init(parent: HotkeyField) {
            self.parent = parent
        }

        deinit {
            stopRecording()
        }

        func startRecording() {
            parent.isRecording = true

            localMonitor = NSEvent.addLocalMonitorForEvents(
                matching: [.keyDown, .flagsChanged]
            ) { [weak self] event in
                guard let self = self, self.parent.isRecording else {
                    return event
                }

                if event.type == .keyDown {
                    // Escape cancels recording
                    if event.keyCode == 53 {
                        self.stopRecording()
                        return nil
                    }
                    let hotkey = self.buildHotkeyFromKeyDown(event)
                    self.parent.hotkeyString = hotkey
                    self.stopRecording()
                    return nil
                }

                if event.type == .flagsChanged {
                    // Detect modifier-only key press
                    if let modKey = self.modifierKeyName(keyCode: event.keyCode) {
                        self.parent.hotkeyString = modKey
                        self.stopRecording()
                        return nil
                    }
                }

                return event
            }
        }

        func stopRecording() {
            parent.isRecording = false
            if let monitor = localMonitor {
                NSEvent.removeMonitor(monitor)
                localMonitor = nil
            }
        }

        private func buildHotkeyFromKeyDown(_ event: NSEvent) -> String {
            var parts: [String] = []

            let mods = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
            if mods.contains(.control) { parts.append("ctrl") }
            if mods.contains(.option) { parts.append("alt") }
            if mods.contains(.shift) { parts.append("shift") }
            if mods.contains(.command) { parts.append("cmd") }

            let keyName = keyCodeToName(event.keyCode)
            parts.append(keyName)

            return parts.joined(separator: "+")
        }

        private func modifierKeyName(keyCode: UInt16) -> String? {
            switch keyCode {
            case 55: return "cmd_l"
            case 54: return "cmd_r"
            case 56: return "shift_l"
            case 60: return "shift_r"
            case 58: return "alt_l"
            case 61: return "alt_r"
            case 59: return "ctrl_l"
            case 62: return "ctrl_r"
            default: return nil
            }
        }

        private func keyCodeToName(_ keyCode: UInt16) -> String {
            switch Int(keyCode) {
            case kVK_Space: return "space"
            case kVK_Return: return "enter"
            case kVK_Tab: return "tab"
            case kVK_Delete: return "backspace"
            case kVK_ForwardDelete: return "delete"
            case kVK_Escape: return "esc"
            case kVK_UpArrow: return "up"
            case kVK_DownArrow: return "down"
            case kVK_LeftArrow: return "left"
            case kVK_RightArrow: return "right"
            case kVK_Home: return "home"
            case kVK_End: return "end"
            case kVK_PageUp: return "pageup"
            case kVK_PageDown: return "pagedown"
            case kVK_F1: return "f1"
            case kVK_F2: return "f2"
            case kVK_F3: return "f3"
            case kVK_F4: return "f4"
            case kVK_F5: return "f5"
            case kVK_F6: return "f6"
            case kVK_F7: return "f7"
            case kVK_F8: return "f8"
            case kVK_F9: return "f9"
            case kVK_F10: return "f10"
            case kVK_F11: return "f11"
            case kVK_F12: return "f12"
            case kVK_ANSI_A: return "a"
            case kVK_ANSI_B: return "b"
            case kVK_ANSI_C: return "c"
            case kVK_ANSI_D: return "d"
            case kVK_ANSI_E: return "e"
            case kVK_ANSI_F: return "f"
            case kVK_ANSI_G: return "g"
            case kVK_ANSI_H: return "h"
            case kVK_ANSI_I: return "i"
            case kVK_ANSI_J: return "j"
            case kVK_ANSI_K: return "k"
            case kVK_ANSI_L: return "l"
            case kVK_ANSI_M: return "m"
            case kVK_ANSI_N: return "n"
            case kVK_ANSI_O: return "o"
            case kVK_ANSI_P: return "p"
            case kVK_ANSI_Q: return "q"
            case kVK_ANSI_R: return "r"
            case kVK_ANSI_S: return "s"
            case kVK_ANSI_T: return "t"
            case kVK_ANSI_U: return "u"
            case kVK_ANSI_V: return "v"
            case kVK_ANSI_W: return "w"
            case kVK_ANSI_X: return "x"
            case kVK_ANSI_Y: return "y"
            case kVK_ANSI_Z: return "z"
            case kVK_ANSI_0: return "0"
            case kVK_ANSI_1: return "1"
            case kVK_ANSI_2: return "2"
            case kVK_ANSI_3: return "3"
            case kVK_ANSI_4: return "4"
            case kVK_ANSI_5: return "5"
            case kVK_ANSI_6: return "6"
            case kVK_ANSI_7: return "7"
            case kVK_ANSI_8: return "8"
            case kVK_ANSI_9: return "9"
            case kVK_ANSI_Minus: return "-"
            case kVK_ANSI_Equal: return "="
            case kVK_ANSI_LeftBracket: return "["
            case kVK_ANSI_RightBracket: return "]"
            case kVK_ANSI_Backslash: return "\\"
            case kVK_ANSI_Semicolon: return ";"
            case kVK_ANSI_Quote: return "'"
            case kVK_ANSI_Comma: return ","
            case kVK_ANSI_Period: return "."
            case kVK_ANSI_Slash: return "/"
            case kVK_ANSI_Grave: return "`"
            default: return "key\(keyCode)"
            }
        }
    }
}

// MARK: - Custom NSTextField for click handling

class HotkeyNSTextField: NSTextField {
    weak var coordinator: HotkeyField.Coordinator?

    override var acceptsFirstResponder: Bool { true }

    override func mouseDown(with event: NSEvent) {
        coordinator?.startRecording()
    }

    override func keyDown(with event: NSEvent) {
        // Swallow - handled by monitor
    }

    override func resignFirstResponder() -> Bool {
        coordinator?.stopRecording()
        return super.resignFirstResponder()
    }
}

// MARK: - Display & Conflict Helpers

private func humanReadable(_ hotkey: String) -> String {
    if hotkey.isEmpty { return "Click to record" }

    let parts = hotkey.split(separator: "+").map(String.init)
    return parts.map { part in
        switch part {
        case "cmd": return "\u{2318}"
        case "cmd_l": return "\u{2318}L"
        case "cmd_r": return "\u{2318}R"
        case "ctrl": return "\u{2303}"
        case "ctrl_l": return "\u{2303}L"
        case "ctrl_r": return "\u{2303}R"
        case "alt": return "\u{2325}"
        case "alt_l": return "\u{2325}L"
        case "alt_r": return "\u{2325}R"
        case "shift": return "\u{21E7}"
        case "shift_l": return "\u{21E7}L"
        case "shift_r": return "\u{21E7}R"
        case "space": return "Space"
        case "enter": return "\u{21A9}"
        case "tab": return "\u{21E5}"
        case "backspace": return "\u{232B}"
        case "delete": return "\u{2326}"
        case "esc": return "\u{238B}"
        case "up": return "\u{2191}"
        case "down": return "\u{2193}"
        case "left": return "\u{2190}"
        case "right": return "\u{2192}"
        default: return part.uppercased()
        }
    }.joined(separator: " ")
}

private let systemShortcuts: [String: String] = [
    "cmd+space": "Spotlight",
    "cmd+tab": "App Switcher",
    "cmd+q": "Quit App",
    "cmd+w": "Close Window",
    "cmd+h": "Hide App",
    "cmd+m": "Minimize Window",
    "cmd+,": "Preferences",
    "cmd+c": "Copy",
    "cmd+v": "Paste",
    "cmd+x": "Cut",
    "cmd+z": "Undo",
    "cmd+a": "Select All",
    "cmd+s": "Save",
    "ctrl+space": "Input Source",
    "ctrl+up": "Mission Control",
    "ctrl+down": "App Windows",
    "ctrl+left": "Move Space Left",
    "ctrl+right": "Move Space Right",
    "cmd+shift+3": "Screenshot",
    "cmd+shift+4": "Screenshot Region",
    "cmd+shift+5": "Screenshot Options",
]

private func checkConflict(_ hotkey: String) -> String? {
    let normalized = hotkey.lowercased()
    if let system = systemShortcuts[normalized] {
        return "Conflicts with \(system)"
    }
    return nil
}
