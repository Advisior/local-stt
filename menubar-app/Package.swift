// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "claude-stt-menubar",
    platforms: [.macOS(.v14)],
    targets: [
        // Everything testable lives in the library; the executable only
        // starts NSApplication so tests can import the menu and pane models.
        .target(
            name: "LocalSTTCore",
            path: "Sources/LocalSTTCore",
            resources: [
                .copy("Resources/advisior_logo.png")
            ]
        ),
        .executableTarget(
            name: "ClaudeSTTMenubar",
            dependencies: ["LocalSTTCore"],
            path: "Sources/ClaudeSTTMenubar"
        ),
        .testTarget(
            name: "LocalSTTCoreTests",
            dependencies: ["LocalSTTCore"],
            path: "Tests/LocalSTTCoreTests"
        ),
    ],
    // Swift 6 tools for Swift Testing, Swift 5 language mode to avoid
    // strict-concurrency churn in existing AppKit code.
    swiftLanguageModes: [.v5]
)
