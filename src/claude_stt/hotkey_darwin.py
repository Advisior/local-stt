"""macOS key event intercept for HotkeyListener: swallow a triggered hotkey's keys."""

# macOS device-dependent modifier flag bits (NX_DEVICE*KEYMASK) by virtual
# keycode. The generic masks cannot tell left from right while the other side
# is held, so a flagsChanged event is classified with these.
_MAC_MODIFIER_FLAG_BITS = {
    59: 0x1, 62: 0x2000,  # ctrl left/right
    56: 0x2, 60: 0x4,  # shift left/right
    55: 0x8, 54: 0x10,  # cmd left/right
    58: 0x20, 61: 0x40,  # alt left/right
}


class MacInterceptMixin:
    """Needs _lock, _logger, _bindings, _suppressed_vks, _held_char_vks,
    _pending_injected, _own_pid, on_other_key, _handle_press and
    _handle_release from HotkeyListener."""

    def _intercept_event(self, event_type, event):
        """macOS-only: swallow the keys of a triggered hotkey, pass everything else.

        pynput calls this after _on_press/_on_release have handled the same
        event, so the bindings' active state is already up to date. Events this
        process injected itself (Cmd+V, typed text, undo Backspaces) pass
        untouched and change no state.
        """
        try:
            from Quartz import (
                CGEventGetIntegerValueField,
                kCGEventFlagsChanged,
                kCGEventKeyDown,
                kCGEventSourceUnixProcessID,
                kCGKeyboardEventAutorepeat,
                kCGKeyboardEventKeycode,
            )
            pending, self._pending_injected = self._pending_injected, []
            source_pid = CGEventGetIntegerValueField(event, kCGEventSourceUnixProcessID)
            if pending and source_pid == self._own_pid:
                return event  # sent by this process: no state change, no invalidation
            for is_press, key in pending:  # injected by another process
                (self._handle_press if is_press else self._handle_release)(key)

            vk = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
            is_repeat = CGEventGetIntegerValueField(event, kCGKeyboardEventAutorepeat) != 0
            is_key_down = event_type == kCGEventKeyDown
            if event_type == kCGEventFlagsChanged:
                is_key_down = self._modifier_is_down(event, vk)
            with self._lock:
                suppress = self._should_suppress(vk, is_key_down, is_repeat=is_repeat)
            if suppress:
                self._logger.debug("Intercept: suppressing vk=%d", vk)
                return None
            if event_type == kCGEventKeyDown and self.on_other_key is not None:
                self.on_other_key()
        except Exception:
            self._logger.exception("Intercept error")
        return event

    def _modifier_is_down(self, event, vk: int) -> bool:
        """Press or release of a flagsChanged event, from the key's own flag bit.

        Falls back to "release" (the behavior before #41) for keycodes without a
        known bit or when the flags cannot be read.
        """
        bit = _MAC_MODIFIER_FLAG_BITS.get(vk)
        if bit is None:
            self._logger.debug("Intercept: no device flag bit for vk=%d, reading it as release", vk)
            return False
        try:
            from Quartz import CGEventGetFlags

            return bool(CGEventGetFlags(event) & bit)
        except Exception as exc:
            self._logger.debug("Intercept: cannot read event flags for vk=%d: %s", vk, exc)
            return False

    def _binding_has_vk(self, binding, vk: int) -> bool:
        if vk in binding.vks:
            return True
        return any(self._held_char_vks.get(k) == vk for k in binding.keys)

    def _should_suppress(self, vk: int, is_key_down: bool, is_repeat: bool = False) -> bool:
        """Whether a key event belongs to a triggered hotkey. Call with the lock held.

        A key is swallowed from the press that completes the full combination
        until its own release, even if a modifier is let go first. Matching the
        keycode alone would swallow every plain Space system-wide when the
        hotkey is ctrl+shift+space.
        """
        if vk in self._suppressed_vks:
            if not is_key_down:
                self._suppressed_vks.discard(vk)  # key-up or modifier release
                return True
            if is_repeat:
                return True  # still held down
            # Fresh press: its release was missed. Swallow it only if it is part
            # of an active binding again (checked below).
            self._suppressed_vks.discard(vk)
        if any(b.active and self._binding_has_vk(b, vk) for b in self._bindings):
            self._suppressed_vks.add(vk)
            return True
        return False
