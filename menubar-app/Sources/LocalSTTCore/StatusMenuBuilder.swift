import AppKit

/// Turns `MenuItemSpec` rows into `NSMenuItem`s. Every item keeps its spec id
/// in `identifier`, so an open menu can be refreshed in place.
enum StatusMenuBuilder {
    /// Wraps a `MenuAction` for `NSMenuItem.representedObject`.
    final class ActionBox: NSObject {
        let action: MenuAction
        init(_ action: MenuAction) { self.action = action }
    }

    static func populate(_ menu: NSMenu, with specs: [MenuItemSpec], target: AnyObject?, action: Selector?) {
        menu.autoenablesItems = false
        menu.removeAllItems()
        for spec in specs {
            menu.addItem(makeItem(spec, target: target, action: action))
        }
    }

    /// Updates titles and states in place while the ids match; rebuilds the
    /// items otherwise (for example when private mode ends while the menu is open).
    static func update(_ menu: NSMenu, with specs: [MenuItemSpec], target: AnyObject?, action: Selector?) {
        guard menu.items.map({ $0.identifier?.rawValue }) == specs.map({ $0.id }) else {
            populate(menu, with: specs, target: target, action: action)
            return
        }
        for (item, spec) in zip(menu.items, specs) {
            apply(spec, to: item)
            if let sub = spec.submenu, let submenu = item.submenu {
                update(submenu, with: sub, target: target, action: action)
            }
        }
    }

    private static func makeItem(_ spec: MenuItemSpec, target: AnyObject?, action: Selector?) -> NSMenuItem {
        let item: NSMenuItem
        switch spec.kind {
        case .separator:
            item = .separator()
        case .sectionHeader:
            item = .sectionHeader(title: spec.title)
        case .header, .item:
            item = NSMenuItem(title: spec.title, action: nil, keyEquivalent: spec.keyEquivalent)
            if spec.action != nil {
                item.target = target
                item.action = action
            }
        }
        item.identifier = NSUserInterfaceItemIdentifier(spec.id)
        if let sub = spec.submenu {
            let submenu = NSMenu(title: spec.title)
            populate(submenu, with: sub, target: target, action: action)
            item.submenu = submenu
        }
        apply(spec, to: item)
        return item
    }

    private static func apply(_ spec: MenuItemSpec, to item: NSMenuItem) {
        guard spec.kind != .separator else { return }
        if item.title != spec.title { item.title = spec.title }
        item.isEnabled = spec.isEnabled
        item.state = spec.isChecked ? .on : .off
        item.representedObject = spec.action.map(ActionBox.init)
        if let symbol = spec.symbol {
            item.image = NSImage(systemSymbolName: symbol, accessibilityDescription: nil)
        } else {
            item.image = nil
        }
        if spec.kind == .header {
            // A disabled item would draw dimmed. The attributed title keeps the
            // state readable; `title` stays plain for VoiceOver and updates.
            if #available(macOS 14.4, *) {
                item.attributedTitle = headerTitle(spec.title, subtitle: nil)
                item.subtitle = spec.subtitle
            } else {
                item.attributedTitle = headerTitle(spec.title, subtitle: spec.subtitle)
            }
        }
    }

    private static func headerTitle(_ title: String, subtitle: String?) -> NSAttributedString {
        let text = NSMutableAttributedString(string: title, attributes: [
            .font: NSFont.menuFont(ofSize: 0).withWeight(.semibold),
            .foregroundColor: NSColor.labelColor,
        ])
        if let subtitle {
            text.append(NSAttributedString(string: "\n" + subtitle, attributes: [
                .font: NSFont.menuFont(ofSize: NSFont.smallSystemFontSize),
                .foregroundColor: NSColor.secondaryLabelColor,
            ]))
        }
        return text
    }
}

private extension NSFont {
    func withWeight(_ weight: NSFont.Weight) -> NSFont {
        NSFont.systemFont(ofSize: pointSize, weight: weight)
    }
}
