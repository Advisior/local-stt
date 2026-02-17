import AVFoundation
import Combine
import Foundation

class DaemonManager: ObservableObject {
    @Published var isRunning: Bool = false
    @Published var permissionsReady: Bool = false

    private var timer: Timer?

    private var pidFileURL: URL {
        ConfigManager.configDir.appendingPathComponent("daemon.pid")
    }

    init() {
        checkStatus()
        checkPermissions()
        // Ensure timer is on the main run loop (C2 fix)
        DispatchQueue.main.async { [weak self] in
            self?.timer = Timer.scheduledTimer(
                withTimeInterval: 2.0, repeats: true
            ) { [weak self] _ in
                // File I/O off main thread (C2 fix)
                DispatchQueue.global(qos: .utility).async {
                    self?.checkStatus()
                }
            }
        }
    }

    deinit {
        timer?.invalidate()
        timer = nil
    }

    // MARK: - Permissions

    /// All permissions required for Local-STT to function:
    /// 1. Microphone - for audio capture (AVCaptureDevice)
    /// 2. Accessibility - for keyboard monitoring via pynput (AXIsProcessTrusted)
    /// Input Monitoring and Automation (System Events) are triggered by the OS
    /// when pynput and text injection first run.

    var hasMicrophoneAccess: Bool {
        AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
    }

    var hasAccessibilityAccess: Bool {
        AXIsProcessTrusted()
    }

    func checkPermissions() {
        let ready = hasMicrophoneAccess && hasAccessibilityAccess
        if ready != permissionsReady {
            DispatchQueue.main.async { [weak self] in
                self?.permissionsReady = ready
            }
        }
    }

    /// Request all required permissions in sequence.
    /// Call this before starting the daemon for the first time.
    func requestAllPermissions(completion: @escaping (Bool) -> Void) {
        // Step 1: Microphone
        requestMicrophoneAccess { [weak self] micGranted in
            guard micGranted else {
                completion(false)
                return
            }

            // Step 2: Accessibility (triggers system dialog)
            DispatchQueue.main.async {
                self?.requestAccessibilityAccess()
                // Accessibility dialog is non-blocking (user must go to System Settings)
                // We proceed anyway - the daemon will warn if not granted
                self?.checkPermissions()
                completion(true)
            }
        }
    }

    func requestMicrophoneAccess(completion: @escaping (Bool) -> Void) {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            completion(true)
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .audio) { granted in
                completion(granted)
            }
        case .denied, .restricted:
            NSLog("Local-STT: Microphone access denied. Open System Settings > Privacy & Security > Microphone")
            completion(false)
        @unknown default:
            completion(false)
        }
    }

    private func requestAccessibilityAccess() {
        if !AXIsProcessTrusted() {
            // This shows the system dialog pointing user to System Settings > Accessibility
            let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue(): true] as CFDictionary
            AXIsProcessTrustedWithOptions(options)
        }
    }

    // MARK: - Status

    func checkStatus() {
        let running = isDaemonRunning()
        if running != isRunning {
            DispatchQueue.main.async { [weak self] in
                self?.isRunning = running
            }
        }
    }

    private func isDaemonRunning() -> Bool {
        guard let pid = readPID() else { return false }
        return kill(pid, 0) == 0
    }

    private func readPID() -> pid_t? {
        guard let data = try? Data(contentsOf: pidFileURL),
              let content = String(data: data, encoding: .utf8)?
                  .trimmingCharacters(in: .whitespacesAndNewlines)
        else { return nil }

        // Try JSON format: {"pid": 12345, ...}
        if let jsonData = content.data(using: .utf8),
           let json = try? JSONSerialization.jsonObject(with: jsonData)
               as? [String: Any],
           let pid = json["pid"] as? Int, pid > 0 {
            return pid_t(pid)
        }

        // Plain number
        if let pid = Int(content), pid > 0 {
            return pid_t(pid)
        }

        return nil
    }

    // MARK: - Control

    /// Start the daemon.
    /// - Parameter promptForPermissions: If true, show system dialogs for missing permissions.
    ///   Set to false for auto-start on app launch to avoid blocking dialogs.
    func startDaemon(promptForPermissions: Bool = true) {
        let python = DaemonManager.findPython()
        guard FileManager.default.fileExists(atPath: python.path) else {
            NSLog("Local-STT: Python not found at %@", python.path)
            return
        }

        if promptForPermissions {
            // Manual start: request all permissions, show dialogs if needed
            requestAllPermissions { [weak self] granted in
                guard granted else {
                    NSLog("Local-STT: Required permissions not granted")
                    return
                }
                self?.launchDaemon(python: python)
            }
        } else {
            // Auto-start: just check mic silently, don't prompt for Accessibility
            if hasMicrophoneAccess {
                checkPermissions()
                launchDaemon(python: python)
            } else {
                // Mic not granted yet - request it (this is non-intrusive)
                requestMicrophoneAccess { [weak self] granted in
                    guard granted else { return }
                    self?.checkPermissions()
                    self?.launchDaemon(python: python)
                }
            }
        }
    }

    private func launchDaemon(python: URL) {
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let process = Process()
            process.executableURL = python
            process.arguments = ["-m", "claude_stt.cli", "start", "--background"]
            process.standardOutput = FileHandle.nullDevice
            process.standardError = FileHandle.nullDevice

            // Use offline mode for HuggingFace Hub after first model download.
            // Prevents network requests on every daemon start.
            var env = ProcessInfo.processInfo.environment
            env["HF_HUB_OFFLINE"] = "1"
            process.environment = env

            do {
                try process.run()
            } catch {
                NSLog("Local-STT: Failed to start daemon: %@", error.localizedDescription)
                return
            }

            // Wait with timeout to avoid blocking forever (C3 fix)
            let waitGroup = DispatchGroup()
            waitGroup.enter()
            DispatchQueue.global(qos: .utility).async {
                process.waitUntilExit()
                waitGroup.leave()
            }
            if waitGroup.wait(timeout: .now() + 30.0) == .timedOut {
                NSLog("Local-STT: Daemon start timed out after 30s")
                process.terminate()
            }

            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                self?.checkStatus()
                self?.checkPermissions()
            }
        }
    }

    func stopDaemon(completion: (() -> Void)? = nil) {
        let python = DaemonManager.findPython()
        guard FileManager.default.fileExists(atPath: python.path) else {
            NSLog("Local-STT: Python not found at %@, falling back to SIGTERM", python.path)
            if let pid = readPID() {
                kill(pid, SIGTERM)
            }
            completion?()
            return
        }

        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let process = Process()
            process.executableURL = python
            process.arguments = ["-m", "claude_stt.cli", "stop"]
            process.standardOutput = FileHandle.nullDevice
            process.standardError = FileHandle.nullDevice
            do {
                try process.run()
            } catch {
                NSLog("Local-STT: Failed to stop daemon: %@", error.localizedDescription)
                DispatchQueue.main.async { completion?() }
                return
            }
            process.waitUntilExit()

            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                self?.checkStatus()
                completion?()
            }
        }
    }

    func toggleRecording() {
        guard let pid = readPID() else { return }
        kill(pid, SIGUSR1)
    }

    /// Restart daemon with proper sequencing (C4 fix: wait for stop before start)
    func restartDaemon() {
        stopDaemon { [weak self] in
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                self?.startDaemon()
            }
        }
    }

    // MARK: - Python detection

    private static var _cachedPython: URL?

    static func findPython() -> URL {
        if let cached = _cachedPython {
            return cached
        }
        let result = _findPython()
        _cachedPython = result
        return result
    }

    private static func _findPython() -> URL {
        let fm = FileManager.default

        // 1. Environment override
        if let envPath = ProcessInfo.processInfo.environment["CLAUDE_STT_VENV"] {
            let python = URL(fileURLWithPath: envPath)
                .appendingPathComponent("bin/python")
            if fm.fileExists(atPath: python.path) {
                return python
            }
            NSLog("Local-STT: CLAUDE_STT_VENV set but python not found at %@", python.path)
        }

        // 2. Relative to the app's executable (e.g. app lives inside the project)
        if let execPath = Bundle.main.executableURL?
            .deletingLastPathComponent() {
            var dir = execPath
            for _ in 0..<5 {
                let candidate = dir.appendingPathComponent(".venv/bin/python")
                if fm.fileExists(atPath: candidate.path) {
                    return candidate
                }
                dir = dir.deletingLastPathComponent()
            }
        }

        // 3. Home directory: ~/Development/claude-stt/.venv/bin/python
        let homePython = fm.homeDirectoryForCurrentUser
            .appendingPathComponent("Development/claude-stt/.venv/bin/python")
        if fm.fileExists(atPath: homePython.path) {
            return homePython
        }

        // 4. Fallback: system python
        let fallback = URL(fileURLWithPath: "/usr/bin/python3")
        if !fm.fileExists(atPath: fallback.path) {
            NSLog("Local-STT: No Python found (checked CLAUDE_STT_VENV, app-relative, ~/Development/claude-stt/.venv, /usr/bin/python3)")
        }
        return fallback
    }
}
