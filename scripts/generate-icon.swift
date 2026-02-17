#!/usr/bin/env swift
import AppKit

let projectDir = CommandLine.arguments.count > 1
    ? CommandLine.arguments[1]
    : String(URL(fileURLWithPath: #file).deletingLastPathComponent()
        .deletingLastPathComponent().path)

let iconsetPath = "\(projectDir)/dist/LocalSTT.iconset"
let icnsPath = "\(projectDir)/dist/AppIcon.icns"

let iconFiles: [(name: String, px: Int)] = [
    ("icon_16x16.png",      16),
    ("icon_16x16@2x.png",   32),
    ("icon_32x32.png",      32),
    ("icon_32x32@2x.png",   64),
    ("icon_128x128.png",    128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png",    256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png",    512),
    ("icon_512x512@2x.png", 1024),
]

// Create iconset directory
let fm = FileManager.default
try? fm.removeItem(atPath: iconsetPath)
try! fm.createDirectory(atPath: iconsetPath, withIntermediateDirectories: true)

for entry in iconFiles {
    let image = renderIcon(pixelSize: entry.px)
    savePNG(image: image, to: "\(iconsetPath)/\(entry.name)")
}

print("Generated iconset at \(iconsetPath)")

// --- Rendering ---

func renderIcon(pixelSize: Int) -> NSImage {
    let s = CGFloat(pixelSize)
    let image = NSImage(size: NSSize(width: s, height: s))

    image.lockFocus()

    let ctx = NSGraphicsContext.current!
    ctx.imageInterpolation = .high
    ctx.shouldAntialias = true

    // 1. Squircle background with gradient
    let r = s * 0.224
    let bg = NSBezierPath(roundedRect: NSRect(x: 0, y: 0, width: s, height: s),
                          xRadius: r, yRadius: r)

    let grad = NSGradient(colors: [
        NSColor(srgbRed: 0.055, green: 0.082, blue: 0.153, alpha: 1),  // #0E1527 deep navy
        NSColor(srgbRed: 0.075, green: 0.380, blue: 0.400, alpha: 1),  // #136166 rich teal
        NSColor(srgbRed: 0.110, green: 0.540, blue: 0.500, alpha: 1),  // #1C8A80 bright teal
    ], atLocations: [0.0, 0.6, 1.0], colorSpace: .sRGB)!
    grad.draw(in: bg, angle: 75)

    // 2. Subtle inner glow at top
    let glowPath = NSBezierPath(roundedRect: NSRect(x: s*0.15, y: s*0.5, width: s*0.7, height: s*0.45),
                                xRadius: s*0.2, yRadius: s*0.2)
    let glow = NSGradient(colors: [
        NSColor(white: 1.0, alpha: 0.08),
        NSColor(white: 1.0, alpha: 0.0),
    ])!
    glow.draw(in: glowPath, angle: 90)

    // 3. Microphone SF Symbol in white
    let pointSize = max(s * 0.42, 10)
    let config = NSImage.SymbolConfiguration(pointSize: pointSize, weight: .medium)
        .applying(NSImage.SymbolConfiguration(hierarchicalColor: .white))

    if let mic = NSImage(systemSymbolName: "mic.fill", accessibilityDescription: nil)?
        .withSymbolConfiguration(config) {
        let w = mic.size.width
        let h = mic.size.height
        let x = (s - w) / 2
        let y = (s - h) / 2
        mic.draw(in: NSRect(x: x, y: y, width: w, height: h),
                 from: .zero, operation: .sourceOver, fraction: 1.0)
    }

    image.unlockFocus()
    return image
}

func savePNG(image: NSImage, to path: String) {
    guard let tiff = image.tiffRepresentation,
          let bmp = NSBitmapImageRep(data: tiff),
          let png = bmp.representation(using: .png, properties: [:])
    else { return }
    try! png.write(to: URL(fileURLWithPath: path))
}
