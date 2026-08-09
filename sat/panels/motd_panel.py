"""Message of the day editing: read, edit, save (with automatic backup)
and restore on the current host."""

import wx

from sat.announce import announce
from sat.util import run_in_thread

DEFAULT_MOTD = "/etc/motd"


class MotdPanel(wx.Panel):
    def __init__(self, parent, frame):
        super().__init__(parent)
        self.frame = frame
        self._build_ui()
        self._bind_events()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        outer = wx.BoxSizer(wx.VERTICAL)

        path_row = wx.BoxSizer(wx.HORIZONTAL)
        path_row.Add(wx.StaticText(self, label="MOTD path:"), 0,
                     wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.path_text = wx.TextCtrl(self, value=DEFAULT_MOTD)
        path_row.Add(self.path_text, 1, wx.EXPAND)
        self.read_btn = wx.Button(self, label="&Read")
        path_row.Add(self.read_btn, 0, wx.LEFT, 12)
        outer.Add(path_row, 0, wx.EXPAND | wx.ALL, 8)

        note = ("Note: on Ubuntu and Debian, dynamic banners are generated "
                "from /etc/update-motd.d and may overwrite this file on "
                "login. Editing /etc/motd works best on servers that use "
                "a static banner.")
        outer.Add(wx.StaticText(self, label=note), 0,
                  wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        outer.Add(wx.StaticText(self, label="MOTD contents:"), 0,
                  wx.LEFT | wx.RIGHT, 8)
        self.editor = wx.TextCtrl(self, style=wx.TE_MULTILINE)
        outer.Add(self.editor, 1, wx.EXPAND | wx.ALL, 8)

        buttons = wx.WrapSizer(wx.HORIZONTAL)
        self.save_btn = wx.Button(self, label="&Save")
        self.preview_btn = wx.Button(self, label="&Preview")
        self.restore_btn = wx.Button(self, label="&Restore backup")
        for btn in (self.save_btn, self.preview_btn, self.restore_btn):
            buttons.Add(btn, 0, wx.RIGHT, 6)
        outer.Add(buttons, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        outer.Add(wx.StaticText(self, label="Output:"), 0,
                  wx.LEFT | wx.RIGHT, 8)
        self.output = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY)
        outer.Add(self.output, 2, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(outer)

    def _bind_events(self):
        self.read_btn.Bind(wx.EVT_BUTTON, lambda e: self.read())
        self.save_btn.Bind(wx.EVT_BUTTON, lambda e: self.save())
        self.preview_btn.Bind(wx.EVT_BUTTON, lambda e: self.preview())
        self.restore_btn.Bind(wx.EVT_BUTTON, lambda e: self.restore())

    # ------------------------------------------------------------- helpers

    def _path(self):
        return self.path_text.GetValue().strip() or DEFAULT_MOTD

    def _set_output(self, text):
        self.output.SetValue(text or "(no output)")

    # -------------------------------------------------------------- actions

    def read(self):
        path = self._path()
        announce(self, f"Reading {path}...")

        def work():
            return self.frame.runner.read_file(path)

        def done(content):
            self.editor.SetValue(content)
            lines = len([ln for ln in content.splitlines() if ln.strip()])
            self._set_output(f"Loaded {path}: {lines} lines.")
            announce(self, f"MOTD loaded from {path}, {lines} lines.")
            self.editor.SetFocus()

        def failed(exc):
            self._set_output(str(exc))
            announce(self, f"Could not read {path}. {exc}")
            wx.MessageBox(str(exc), "Read failed", wx.OK | wx.ICON_ERROR)

        run_in_thread(work, done, failed)

    def save(self):
        path = self._path()
        content = self.editor.GetValue()
        if wx.MessageBox(
                f"Save the MOTD to {path} on {self.frame.runner.describe()}? "
                "The previous version is kept as a .bak file.",
                "Confirm save", wx.YES_NO | wx.ICON_QUESTION) != wx.YES:
            return
        announce(self, f"Saving MOTD to {path}...")

        def work():
            self.frame.runner.write_file(path, content)
            return path

        def done(saved_path):
            self._set_output(f"Saved {saved_path}. A backup was made as "
                             f"{saved_path}.bak.")
            announce(self, f"MOTD saved to {saved_path}. Backup kept as "
                           f"{saved_path}.bak.")

        def failed(exc):
            self._set_output(str(exc))
            announce(self, f"Could not save {path}. {exc}")
            wx.MessageBox(str(exc), "Save failed", wx.OK | wx.ICON_ERROR)

        run_in_thread(work, done, failed)

    def preview(self):
        self._set_output("Preview of the current MOTD:\n\n" +
                         self.editor.GetValue())
        announce(self, "MOTD preview shown in the output area.")

    def restore(self):
        path = self._path()
        if wx.MessageBox(
                f"Restore {path} from the saved backup {path}.bak?",
                "Confirm restore", wx.YES_NO | wx.ICON_QUESTION) != wx.YES:
            return
        announce(self, f"Restoring {path} from backup...")

        def work():
            self.frame.runner.restore_backup(path)
            return self.frame.runner.read_file(path)

        def done(content):
            self.editor.SetValue(content)
            self._set_output(f"Restored {path} from {path}.bak.")
            announce(self, f"Restored {path} from backup.")

        def failed(exc):
            self._set_output(str(exc))
            announce(self, f"Could not restore {path}. {exc}")
            wx.MessageBox(str(exc), "Restore failed", wx.OK | wx.ICON_ERROR)

        run_in_thread(work, done, failed)

    def refresh(self):
        """Nothing to reload automatically: never overwrite the editor."""
        pass

    # ------------------------------------------------------------- external

    def focus_output(self):
        self.output.SetFocus()

    def describe_state(self):
        return f"MOTD editor for {self._path()}"
