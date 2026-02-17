// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "claude-stt-menubar",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "ClaudeSTTMenubar",
            path: "Sources",
            resources: [
                .copy("Resources/advisior_logo.png")
            ]
        )
    ]
)
