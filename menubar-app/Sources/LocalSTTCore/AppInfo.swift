import Foundation

enum AppInfo {
    /// App version, injected by build script via Info.plist or fallback.
    static var version: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString")
            as? String ?? "0.1.0"
    }
}
