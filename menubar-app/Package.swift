// swift-tools-version: 5.9
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
    ]
    // Tools version 5.9 keeps the source installer working with the Xcode 15
    // Command Line Tools. The tests use Swift Testing and need a Swift 6
    // toolchain, which only development and CI require.
)
