# Glossary

Domain terms used in code, tickets and docs.

**Dictation insert**
: The text one transcription put into the focused app, including the trailing space, together with the output mode actually used (`clipboard_paste` or `injection`). Copying to the clipboard alone (`clipboard` mode) is not an insert. Code: `keyboard.InsertResult`, `undo.UndoTracker`.

**Undo window**
: The time after a dictation insert during which the undo hotkey still removes it (`undo_window_seconds`, default 60). Inside the window the insert also stops being undoable once the user presses any non-modifier key, switches the frontmost app, or undoes it once.

**Private mode**
: Timed state, switched on in the Private Mode submenu of the status item menu (15 minutes, 1 hour, until turned off), in which dictations are output but not stored in `history.jsonl`, and pasteboard writes are marked concealed and transient. Stored in `private_mode.json` in the config dir; no file means off, an unreadable file means on. The undo hotkey keeps working, its tracker holds the last insert in memory only. Code: `history.private_mode_active`, `PrivateModeManager`.

**Dictation service**
: The UI name for the Python daemon that holds the hotkeys, records and transcribes. The status item menu starts, restarts and stops it in its "Dictation Service" section. Code: `claude_stt.daemon`, `DaemonManager`, `ServiceState`.
