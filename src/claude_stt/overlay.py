"""Recording HUD for claude-stt (#60), a native macOS panel drawn with PyObjC.

Runs as a subprocess and reads one command per stdin line; the protocol,
the states and the layout rules live in overlay_model.py. This module only
turns a HudState into AppKit views: a non-activating panel with an
NSVisualEffectView (.hudWindow material) shaped as a capsule at the bottom
center of the main screen, system colors only, VoiceOver labels and
announcements, and no animation while Reduce Motion is on.
"""

from __future__ import annotations

import os
import sys
import threading
import time

import AppKit
import Foundation
import objc

if __package__ in (None, ""):  # started as a script by daemon_overlay._start_overlay
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from claude_stt import overlay_model as model
else:
    from . import overlay_model as model

HEIGHT = 36.0
TEXT_VPAD = 9.0  # top and bottom inset of a wrapped text
PADDING = 14.0
SPACING = 10.0
BOTTOM_MARGIN = 22.0
SCREEN_INSET = 40.0
FONT_SIZE = 13.0
SYMBOL_POINT_SIZE = 13.0
DOT_SIZE = 8.0
BAR_WIDTH = 3.0
BAR_GAP = 2.0
METER_MIN, METER_MAX = 3.0, 16.0
FLASH_SECONDS = 1.5
TICK_SECONDS = 0.5

_SYMBOL_TINTS = {
    "checkmark.circle.fill": "systemGreenColor",
    "exclamationmark.triangle.fill": "systemOrangeColor",
}


class _Dispatcher(AppKit.NSObject):
    """Helper to dispatch callables to the main thread."""

    def callBlock_(self, block):
        block()


_dispatcher = None


def _perform_on_main(func, delay=0.0):
    """Schedule a function on the main thread, optionally after a delay."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = _Dispatcher.alloc().init()

    if delay <= 0:
        _dispatcher.performSelectorOnMainThread_withObject_waitUntilDone_(
            b"callBlock:", func, False
        )
    else:
        def _schedule():
            AppKit.NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
                delay, False, lambda _: func()
            )
        _dispatcher.performSelectorOnMainThread_withObject_waitUntilDone_(
            b"callBlock:", _schedule, False
        )


def reduce_motion_enabled() -> bool:
    try:
        return bool(AppKit.NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion())
    except Exception:
        return False


class _DotView(AppKit.NSView):
    """Steady red dot; the system color adapts to appearance and contrast."""

    def drawRect_(self, rect):
        AppKit.NSColor.systemRedColor().set()
        AppKit.NSBezierPath.bezierPathWithOvalInRect_(self.bounds()).fill()


class _MeterView(AppKit.NSView):
    """Level meter: rounded bars, newest level on the right."""

    _heights = objc.ivar()

    def setHeights_(self, heights):
        self._heights = list(heights)
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        AppKit.NSColor.labelColor().colorWithAlphaComponent_(0.75).set()
        mid = self.bounds().size.height / 2
        for i, h in enumerate(self._heights or []):
            x = i * (BAR_WIDTH + BAR_GAP)
            bar = Foundation.NSMakeRect(x, mid - h / 2, BAR_WIDTH, h)
            AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                bar, BAR_WIDTH / 2, BAR_WIDTH / 2
            ).fill()


class _KeyCapView(AppKit.NSView):
    """Hairline key cap around the "esc" label."""

    def drawRect_(self, rect):
        AppKit.NSColor.secondaryLabelColor().colorWithAlphaComponent_(0.4).set()
        path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            AppKit.NSInsetRect(self.bounds(), 0.25, 0.25), 4.0, 4.0
        )
        path.setLineWidth_(0.5)
        path.stroke()


class _CapsuleBorderView(AppKit.NSView):
    """Hairline border around the capsule, drawn above the material."""

    def drawRect_(self, rect):
        AppKit.NSColor.labelColor().colorWithAlphaComponent_(0.14).set()
        bounds = AppKit.NSInsetRect(self.bounds(), 0.25, 0.25)
        radius = min(bounds.size.height, HEIGHT) / 2
        path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bounds, radius, radius)
        path.setLineWidth_(0.5)
        path.stroke()

    def hitTest_(self, point):
        return None


def _label(text: str, font, color):
    field = AppKit.NSTextField.labelWithString_(text)
    field.setFont_(font)
    field.setTextColor_(color)
    field.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
    field.sizeToFit()
    return field


def _symbol_view(item):
    image = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(item.symbol, item.label)
    view = AppKit.NSImageView.alloc().initWithFrame_(Foundation.NSMakeRect(0, 0, 16, 16))
    if image is not None:
        config = AppKit.NSImageSymbolConfiguration.configurationWithPointSize_weight_(
            SYMBOL_POINT_SIZE, AppKit.NSFontWeightMedium
        )
        image = image.imageWithSymbolConfiguration_(config)
        view.setImage_(image)
        view.setFrameSize_(image.size())
    tint = _SYMBOL_TINTS.get(item.symbol)
    color = getattr(AppKit.NSColor, tint)() if tint else (
        AppKit.NSColor.secondaryLabelColor() if item.secondary else AppKit.NSColor.labelColor()
    )
    view.setContentTintColor_(color)
    return view


def build_item_view(item, levels, reduce_motion: bool):
    """One AppKit view for one model Item, sized to its content."""
    secondary = AppKit.NSColor.secondaryLabelColor()
    if item.kind == "dot":
        view = _DotView.alloc().initWithFrame_(Foundation.NSMakeRect(0, 0, DOT_SIZE, DOT_SIZE))
        role = AppKit.NSAccessibilityImageRole
    elif item.kind == "symbol":
        view = _symbol_view(item)
        role = AppKit.NSAccessibilityImageRole
    elif item.kind == "spinner":
        view = AppKit.NSProgressIndicator.alloc().initWithFrame_(Foundation.NSMakeRect(0, 0, 16, 16))
        view.setStyle_(AppKit.NSProgressIndicatorStyleSpinning)
        view.setControlSize_(AppKit.NSControlSizeSmall)
        view.setIndeterminate_(True)
        if not reduce_motion:
            view.startAnimation_(None)
        role = AppKit.NSAccessibilityProgressIndicatorRole
    elif item.kind == "meter":
        width = model.METER_BARS * BAR_WIDTH + (model.METER_BARS - 1) * BAR_GAP
        view = _MeterView.alloc().initWithFrame_(Foundation.NSMakeRect(0, 0, width, METER_MAX))
        view.setHeights_(model.bar_heights(levels, model.METER_BARS, METER_MIN, METER_MAX))
        role = AppKit.NSAccessibilityLevelIndicatorRole
    elif item.kind == "time":
        font = AppKit.NSFont.monospacedDigitSystemFontOfSize_weight_(FONT_SIZE, AppKit.NSFontWeightRegular)
        view = _label(item.text, font, secondary)
        role = AppKit.NSAccessibilityStaticTextRole
    elif item.kind == "key":
        font = AppKit.NSFont.systemFontOfSize_weight_(11.0, AppKit.NSFontWeightMedium)
        text = _label(item.text, font, secondary)
        size = text.frame().size
        view = _KeyCapView.alloc().initWithFrame_(
            Foundation.NSMakeRect(0, 0, size.width + 10, size.height + 2)
        )
        text.setFrameOrigin_(Foundation.NSMakePoint(5, 1))
        text.setAccessibilityElement_(False)
        view.addSubview_(text)
        role = AppKit.NSAccessibilityStaticTextRole
    else:  # text
        view = _label(item.text, AppKit.NSFont.systemFontOfSize_(FONT_SIZE), AppKit.NSColor.labelColor())
        role = AppKit.NSAccessibilityStaticTextRole
    view.setAccessibilityElement_(True)
    view.setAccessibilityRole_(role)
    view.setAccessibilityLabel_(item.label)
    return view


class HudView(AppKit.NSVisualEffectView):
    """The capsule: HUD material, rounded to half its height."""

    def initWithFrame_(self, frame):
        self = objc.super(HudView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.setMaterial_(AppKit.NSVisualEffectMaterialHUDWindow)
        self.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
        self.setState_(AppKit.NSVisualEffectStateActive)
        self.setWantsLayer_(True)
        self.layer().setMasksToBounds_(True)
        self.setAccessibilityElement_(True)
        self.setAccessibilityRole_(AppKit.NSAccessibilityGroupRole)
        self.setAccessibilityLabel_("Dictation")
        return self


def _wrap_label(view, width: float) -> None:
    """Let a text label wrap to ``width`` so nothing is cut off (AC-10)."""
    view.setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
    view.setMaximumNumberOfLines_(0)
    view.setPreferredMaxLayoutWidth_(width)
    view.setFrameSize_(Foundation.NSMakeSize(width, view.fittingSize().height))


def show_items(hud, items, levels, reduce_motion: bool, max_width: float) -> tuple[float, float]:
    """Replace the capsule content with views for ``items``; returns (width, height).

    A text wider than the screen allows wraps onto more lines and the capsule
    grows taller instead of truncating it.
    """
    for sub in list(hud.subviews()):
        sub.removeFromSuperview()
    views = [build_item_view(item, levels, reduce_motion) for item in items]
    widths = [v.frame().size.width for v in views]
    origins, width = model.layout(widths, PADDING, SPACING, max_width=max_width)
    for item, view, x in zip(items, views, origins):
        available = max(0.0, width - PADDING - x)
        if view.frame().size.width > available:  # only when capped by the screen
            if item.kind == "text":
                _wrap_label(view, available)
            else:
                view.setFrameSize_(Foundation.NSMakeSize(available, view.frame().size.height))
    content = max((v.frame().size.height for v in views), default=0.0)
    height = model.capsule_height(content, HEIGHT, TEXT_VPAD)
    for view, x in zip(views, origins):
        size = view.frame().size
        view.setFrameOrigin_(Foundation.NSMakePoint(x, round((height - size.height) / 2)))
        hud.addSubview_(view)
    hud.setFrameSize_(Foundation.NSMakeSize(width, height))
    hud.layer().setCornerRadius_(HEIGHT / 2)
    border = _CapsuleBorderView.alloc().initWithFrame_(hud.bounds())
    border.setAccessibilityElement_(False)
    hud.addSubview_(border)
    return width, height


class RecordingOverlay:
    """Native macOS HUD panel driven by overlay_model states."""

    def __init__(self):
        self._app = AppKit.NSApplication.sharedApplication()
        # Background-only app: no Dock icon, never activates.
        self._app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

        frame = Foundation.NSMakeRect(0, 0, 200, HEIGHT)
        self._panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        self._panel.setLevel_(AppKit.NSStatusWindowLevel)
        self._panel.setOpaque_(False)
        self._panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        self._panel.setHasShadow_(True)
        self._panel.setIgnoresMouseEvents_(True)
        self._panel.setHidesOnDeactivate_(False)
        self._panel.setBecomesKeyOnlyIfNeeded_(True)
        self._panel.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        self._hud = HudView.alloc().initWithFrame_(frame)
        self._panel.setContentView_(self._hud)

        self._state = model.HudState()
        self._generation = 0  # invalidates pending auto-hide and tick timers
        self._last_announced = None

    @property
    def state(self) -> model.HudState:
        return self._state

    def handle(self, command: model.Command) -> None:
        """Apply one protocol command. Main thread only."""
        previous = self._state
        self._state = model.apply(previous, command, now=time.time())
        if self._state.kind == model.HIDDEN:
            self._hide()
            return
        state_changed = command.name != "LEVEL"
        if state_changed:
            self._generation += 1
        self.render()
        if not state_changed:
            return
        self._announce()
        generation = self._generation
        if self._state.kind in (model.DONE, model.HINT):
            _perform_on_main(lambda: self._auto_hide(generation), delay=FLASH_SECONDS)
        elif self._state.kind == model.RECORDING:
            self._schedule_tick(generation)

    def render(self, reduce_motion: bool | None = None, now: float | None = None) -> None:
        """Draw the current state and place the capsule at the bottom center."""
        if reduce_motion is None:
            reduce_motion = reduce_motion_enabled()
        now = time.time() if now is None else now
        items = model.hud_items(self._state, reduce_motion=reduce_motion, now=now)
        screen = AppKit.NSScreen.mainScreen() or AppKit.NSScreen.screens()[0]
        visible = screen.visibleFrame()
        max_width = visible.size.width - SCREEN_INSET
        width, height = show_items(self._hud, items, self._state.levels, reduce_motion, max_width)
        x, y = model.capsule_origin(
            (visible.origin.x, visible.origin.y, visible.size.width, visible.size.height),
            width, height, BOTTOM_MARGIN,
        )
        self._panel.setFrame_display_(Foundation.NSMakeRect(round(x), round(y), width, height), True)
        self._panel.invalidateShadow()
        self._panel.orderFrontRegardless()

    def _announce(self) -> None:
        text = model.announcement(self._state)
        if not text or (text, self._generation) == self._last_announced:
            return
        self._last_announced = (text, self._generation)
        try:
            AppKit.NSAccessibilityPostNotificationWithUserInfo(
                AppKit.NSApp,
                AppKit.NSAccessibilityAnnouncementRequestedNotification,
                {
                    AppKit.NSAccessibilityAnnouncementKey: text,
                    AppKit.NSAccessibilityPriorityKey: AppKit.NSAccessibilityPriorityHigh,
                },
            )
        except Exception:
            pass

    def _schedule_tick(self, generation: int) -> None:
        def tick():
            if generation != self._generation or self._state.kind != model.RECORDING:
                return
            self.render()
            self._schedule_tick(generation)
        _perform_on_main(tick, delay=TICK_SECONDS)

    def _auto_hide(self, generation: int) -> None:
        if generation == self._generation:
            self._state = model.HudState()
            self._hide()

    def _hide(self) -> None:
        self._generation += 1
        self._panel.orderOut_(None)


def _read_stdin(overlay):
    """Read commands from stdin in background thread.

    Always terminates the app when the loop ends, whether via an explicit
    QUIT command, an EOF (stdin closed because the parent process died,
    cleanly or not), or a read error. Without this, a parent crash leaves
    the overlay window stuck on screen forever (stdin EOF ends the `for`
    loop normally, without raising, so a bare except-based exit is not
    enough).
    """
    try:
        for line in sys.stdin:
            command = model.parse_command(line)
            if command is None:
                continue
            if command.name == "QUIT":
                break
            _perform_on_main(lambda c=command: overlay.handle(c))
    except (EOFError, OSError):
        pass
    _perform_on_main(lambda: AppKit.NSApp.terminate_(None))


def main():
    """Entry point when run as subprocess."""
    overlay = RecordingOverlay()

    reader = threading.Thread(target=_read_stdin, args=(overlay,), daemon=True)
    reader.start()

    AppKit.NSApp.run()


if __name__ == "__main__":
    main()
