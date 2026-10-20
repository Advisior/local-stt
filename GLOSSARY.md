# Glossary

Domain terms used in code, tickets and docs.

**Dictation insert**
: The text one transcription put into the focused app, including the trailing space, together with the output mode actually used (`clipboard_paste` or `injection`). Copying to the clipboard alone (`clipboard` mode) is not an insert. Code: `keyboard.InsertResult`, `undo.UndoTracker`.

**Undo window**
: The time after a dictation insert during which the undo hotkey still removes it (`undo_window_seconds`, default 60). Inside the window the insert also stops being undoable once the user presses any non-modifier key, switches the frontmost app, or undoes it once.
