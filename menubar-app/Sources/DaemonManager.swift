import Foundation
import Combine

class DaemonManager: ObservableObject {
    @Published var isRunning: Bool = false

    private var timer: Timer?

    private var pidFileURL: URL {
        ConfigManager.configDir.appendingPathComponent("daemon.pid")
    }

    init() {
        checkStatus()
        timer = Timer.scheduledTimer(
            withTimeInterval: 2.0, repeats: true
        ) { [weak self] _ in
            self?.checkStatus()
        }
    }

    deinit {
        timer?.invalidate()
        timer = nil
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
        // kill(pid, 0) checks if process exists without sending a signal
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

    func startDaemon() {
        let python = DaemonManager.findPython()
        guard FileManager.default.fileExists(atPath: python.path) else {
            NSLog("Claude STT: Python not found at %@", python.path)
            return
        }

        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let process = Process()
            process.executableURL = python
            process.arguments = ["-m", "claude_stt.cli", "start", "--background"]
            process.standardOutput = FileHandle.nullDevice
            process.standardError = FileHandle.nullDevice
            do {
                try process.run()
            } catch {
                NSLog("Claude STT: Failed to start daemon: %@", error.localizedDescription)
                return
            }
            process.waitUntilExit()

            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                self?.checkStatus()
            }
        }
    }

    func stopDaemon() {
        let python = DaemonManager.findPython()
        guard FileManager.default.fileExists(atPath: python.path) else {
            NSLog("Claude STT: Python not found at %@, falling back to SIGTERM", python.path)
            // Fallback: send SIGTERM directly
            if let pid = readPID() {
                kill(pid, SIGTERM)
            }
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
                NSLog("Claude STT: Failed to stop daemon: %@", error.localizedDescription)
                return
            }
            process.waitUntilExit()

            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                self?.checkStatus()
            }
        }
    }

    func toggleRecording() {
        guard let pid = readPID() else { return }
        kill(pid, SIGUSR1)
    }

    func restartDaemon() {
        stopDaemon()
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) { [weak self] in
            self?.startDaemon()
        }
    }

    // MARK: - Python detection

    static func findPython() -> URL {
        let fm = FileManager.default

        // 1. Environment override
        if let envPath = ProcessInfo.processInfo.environment["CLAUDE_STT_VENV"] {
            let python = URL(fileURLWithPath: envPath)
                .appendingPathComponent("bin/python")
            if fm.fileExists(atPath: python.path) {
                return python
            }
            NSLog("Claude STT: CLAUDE_STT_VENV set but python not found at %@", python.path)
        }

        // 2. Relative to the app's executable (e.g. app lives inside the project)
        if let execPath = Bundle.main.executableURL?
            .deletingLastPathComponent() {
            // Walk up to find a .venv sibling directory
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
            NSLog("Claude STT: No Python found (checked CLAUDE_STT_VENV, app-relative, ~/Development/claude-stt/.venv, /usr/bin/python3)")
        }
        return fallback
    }
}
