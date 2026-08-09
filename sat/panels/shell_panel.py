"""Line-based shell: type one command, press Enter, read the output.

A real terminal emulator is hard to use with a screen reader, so SAT
provides a command line instead: every command runs on the current host
and the output is plain text you can arrow through.  This works both
locally and over SSH."""

import wx

from sat.announce import announce
from sat.util import run_in_thread


class ShellPanel(wx.Panel):
    def __init__(self, parent, frame):
        super().__init__(parent)
        self.frame = frame
        self._build_ui()
        self._bind_events()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        outer = wx.BoxSizer(wx.VERTICAL)

        outer.Add(wx.StaticText(
            self,
            label="Type a command and press Enter. It runs on the current "
                  "host."), 0, wx.ALL, 8)

        cmd_row = wx.BoxSizer(wx.HORIZONTAL)
        cmd_row.Add(wx.StaticText(self, label="Command:"), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.command_text = wx.TextCtrl(
            self, style=wx.TE_PROCESS_ENTER)
        cmd_row.Add(self.command_text, 1, wx.EXPAND)
        self.run_btn = wx.Button(self, label="&Run")
        cmd_row.Add(self.run_btn, 0, wx.LEFT, 12)
        outer.Add(cmd_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        outer.Add(wx.StaticText(self, label="Output:"), 0,
                  wx.LEFT | wx.RIGHT, 8)
        self.output = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY)
        outer.Add(self.output, 1, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(outer)

    def _bind_events(self):
        self.run_btn.Bind(wx.EVT_BUTTON, lambda e: self.run_command())
        self.command_text.Bind(wx.EVT_TEXT_ENTER,
                               lambda e: self.run_command())

    # -------------------------------------------------------------- actions

    def run_command(self):
        command = self.command_text.GetValue().strip()
        if not command:
            announce(self, "The command box is empty.")
            self.command_text.SetFocus()
            return
        target = self.frame.runner.describe()
        self._append(f"> {command}  (on {target})\n")
        tokens = command.split()
        use_admin = bool(tokens) and tokens[0] == "sudo"
        if use_admin:
            announce(self, f"Running with sudo using the saved password: "
                           f"{command} on {target}")
        else:
            announce(self, f"Running: {command} on {target}")
        self._execute(command, use_admin)

    def _execute(self, command, use_admin):
        def work():
            if use_admin:
                return self.frame.runner.run_admin(command, timeout=120)
            return self.frame.runner.run(command, timeout=120)

        def done(res):
            body = res.combined or res.error or "(no output)"
            if (not res.ok and not use_admin
                    and self._looks_like_sudo_issue(body)):
                # The user typed a bare sudo command; the SSH session has
                # no terminal, so retry feeding the saved password.
                announce(self, "That sudo command could not read a "
                               "password; retrying with the saved one.")
                self._append("(retrying with sudo using the saved "
                             "password)\n")
                self._execute(command, True)
                return
            self._append(body + "\n")
            announce(self, f"Command finished: {res.summary()}")
            self.command_text.SetFocus()

        run_in_thread(work, done)

    @staticmethod
    def _looks_like_sudo_issue(body):
        low = body.lower()
        return ("a terminal is required" in low
                or "a password is required" in low)

    def _append(self, text):
        current = self.output.GetValue()
        self.output.SetValue(current + text)
        self.output.SetInsertionPointEnd()
        self.output.SetScrollPos(wx.VERTICAL,
                                 self.output.GetScrollRange(wx.VERTICAL))

    def refresh(self):
        announce(self, f"Shell ready. Commands run on {self.frame.runner.describe()}.")

    # ------------------------------------------------------------- external

    def focus_output(self):
        self.output.SetFocus()

    def describe_state(self):
        return f"Shell on {self.frame.runner.describe()}"
