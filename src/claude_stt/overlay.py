"""Recording overlay indicator for claude-stt.

Native macOS overlay using PyObjC (no tkinter needed).
Runs as a subprocess, receives commands via stdin:
  RECORDING         - show recording indicator with timer
  TRANSCRIBING      - switch to "transcribing..." state
  DONE <n>          - flash success with word count, then hide
  CANCEL            - hide immediately
  QUIT              - exit process
"""

from __future__ import annotations

import sys
import threading
import time

import AppKit
import Foundation
import objc


# ── Colors ──
RED = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.94, 0.27, 0.27, 1.0)
RED_DIM = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.67, 0.13, 0.13, 1.0)
AMBER = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.92, 0.70, 0.03, 1.0)
GREEN = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.16, 0.70, 0.05, 1.0)
WHITE = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.89, 0.91, 0.94, 1.0)
GRAY = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.39, 0.46, 0.55, 1.0)

WINDOW_WIDTH = 200
WINDOW_HEIGHT = 50
PADDING = 20


class _Dispatcher(AppKit.NSObject):
    """Helper to dispatch callables to the main thread."""

    def callBlock_(self, block):
        block()


# Singleton dispatcher for main-thread calls
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
        # Dispatch to main thread first, then schedule timer there
        def _schedule():
            AppKit.NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
                delay, False, lambda _: func()
            )
        _dispatcher.performSelectorOnMainThread_withObject_waitUntilDone_(
            b"callBlock:", _schedule, False
        )


class RecordingOverlay:
    """Native macOS floating overlay."""

    def __init__(self):
        self._app = AppKit.NSApplication.sharedApplication()
        # Make it a background-only app (no Dock icon)
        self._app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

        # Create borderless, floating window
        screen = AppKit.NSScreen.mainScreen()
        screen_frame = screen.visibleFrame()
        x = screen_frame.origin.x + screen_frame.size.width - WINDOW_WIDTH - PADDING
        y = screen_frame.origin.y + PADDING
        frame = Foundation.NSMakeRect(x, y, WINDOW_WIDTH, WINDOW_HEIGHT)

        self._window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            AppKit.NSWindowStyleMaskBorderless,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        self._window.setLevel_(AppKit.NSStatusWindowLevel)
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(AppKit.NSColor.clearColor())
        self._window.setHasShadow_(True)
        self._window.setIgnoresMouseEvents_(True)
        self._window.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorStationary
        )

        # Content view with rounded corners
        content = AppKit.NSView.alloc().initWithFrame_(
            Foundation.NSMakeRect(0, 0, WINDOW_WIDTH, WINDOW_HEIGHT)
        )
        content.setWantsLayer_(True)
        content.layer().setCornerRadius_(12.0)
        content.layer().setMasksToBounds_(True)
        content.layer().setBackgroundColor_(
            _cgcolor(0.10, 0.10, 0.18, 0.92)
        )
        content.layer().setBorderColor_(_cgcolor(0.20, 0.20, 0.35, 0.6))
        content.layer().setBorderWidth_(0.5)
        self._content = content
        self._window.setContentView_(content)

        # Dot indicator (circle view)
        self._dot = _DotView.alloc().initWithFrame_(
            Foundation.NSMakeRect(14, 17, 14, 14)
        )
        self._dot.setColor_(RED)
        content.addSubview_(self._dot)

        # Status label
        self._status = AppKit.NSTextField.labelWithString_("")
        self._status.setFrame_(Foundation.NSMakeRect(36, 22, 150, 20))
        self._status.setFont_(AppKit.NSFont.systemFontOfSize_weight_(13, 0.5))
        self._status.setTextColor_(WHITE)
        self._status.setBezeled_(False)
        self._status.setDrawsBackground_(False)
        self._status.setEditable_(False)
        self._status.setSelectable_(False)
        content.addSubview_(self._status)

        # Timer label
        self._timer = AppKit.NSTextField.labelWithString_("")
        self._timer.setFrame_(Foundation.NSMakeRect(36, 6, 150, 16))
        self._timer.setFont_(AppKit.NSFont.systemFontOfSize_(10))
        self._timer.setTextColor_(GRAY)
        self._timer.setBezeled_(False)
        self._timer.setDrawsBackground_(False)
        self._timer.setEditable_(False)
        self._timer.setSelectable_(False)
        content.addSubview_(self._timer)

        # State
        self._state = "hidden"
        self._record_start: float = 0
        self._timer_active = False

    def _show(self):
        self._window.orderFront_(None)

    def _hide(self):
        self._window.orderOut_(None)
        self._state = "hidden"
        self._timer_active = False

    def show_recording(self):
        self._state = "recording"
        self._record_start = time.time()
        self._timer_active = True

        self._content.layer().setBackgroundColor_(_cgcolor(0.10, 0.10, 0.18, 0.92))
        self._dot.setColor_(RED)
        self._status.setStringValue_("Recording...")
        self._status.setTextColor_(WHITE)
        self._timer.setStringValue_("0s")
        self._timer.setTextColor_(GRAY)

        self._show()
        self._schedule_timer_update()

    def _schedule_timer_update(self):
        if not self._timer_active:
            return
        _perform_on_main(self._update_timer, delay=0.5)

    def _update_timer(self):
        if self._state != "recording":
            return
        elapsed = time.time() - self._record_start
        self._timer.setStringValue_(f"{elapsed:.0f}s")

        # Blink dot
        phase = int(elapsed * 2) % 2
        self._dot.setColor_(RED if phase else RED_DIM)
        self._dot.setNeedsDisplay_(True)

        self._schedule_timer_update()

    def show_transcribing(self):
        self._state = "transcribing"
        self._timer_active = False
        elapsed = time.time() - self._record_start

        self._content.layer().setBackgroundColor_(_cgcolor(0.10, 0.10, 0.18, 0.92))
        self._dot.setColor_(AMBER)
        self._dot.setNeedsDisplay_(True)
        self._status.setStringValue_("Transcribing...")
        self._status.setTextColor_(AMBER)
        self._timer.setStringValue_(f"{elapsed:.0f}s audio")
        self._timer.setTextColor_(GRAY)

        self._show()

    def show_done(self, word_count: str):
        self._state = "done"
        self._timer_active = False

        self._content.layer().setBackgroundColor_(_cgcolor(0.05, 0.15, 0.09, 0.92))
        self._dot.setColor_(GREEN)
        self._dot.setNeedsDisplay_(True)
        self._status.setStringValue_(f"\u2713 {word_count} words")
        self._status.setTextColor_(GREEN)
        self._timer.setStringValue_("")

        self._show()
        # Auto-hide after 1.5s
        _perform_on_main(self._hide, delay=1.5)

    def cancel(self):
        self._hide()


class _DotView(AppKit.NSView):
    """A colored circle view."""

    _color = objc.ivar()

    def initWithFrame_(self, frame):
        self = objc.super(_DotView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._color = RED
        return self

    def setColor_(self, color):
        self._color = color

    def drawRect_(self, rect):
        self._color.set()
        path = AppKit.NSBezierPath.bezierPathWithOvalInRect_(self.bounds())
        path.fill()


def _cgcolor(r, g, b, a):
    """Create a CGColor from RGBA."""
    import Quartz
    return Quartz.CGColorCreateGenericRGB(r, g, b, a)


def _read_stdin(overlay):
    """Read commands from stdin in background thread."""
    try:
        for line in sys.stdin:
            cmd = line.strip()
            if not cmd:
                continue
            if cmd == "QUIT":
                _perform_on_main(lambda: AppKit.NSApp.terminate_(None))
                break
            elif cmd == "RECORDING":
                _perform_on_main(overlay.show_recording)
            elif cmd == "TRANSCRIBING":
                _perform_on_main(overlay.show_transcribing)
            elif cmd.startswith("DONE"):
                parts = cmd.split(maxsplit=1)
                count = parts[1] if len(parts) > 1 else "0"
                _perform_on_main(lambda c=count: overlay.show_done(c))
            elif cmd == "CANCEL":
                _perform_on_main(overlay.cancel)
    except (EOFError, OSError):
        _perform_on_main(lambda: AppKit.NSApp.terminate_(None))


def main():
    """Entry point when run as subprocess."""
    overlay = RecordingOverlay()

    reader = threading.Thread(target=_read_stdin, args=(overlay,), daemon=True)
    reader.start()

    AppKit.NSApp.run()


if __name__ == "__main__":
    main()
