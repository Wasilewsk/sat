"""Systemd unit management: list, filter, start, stop, restart, enable,
disable, mask, status and logs."""

import shlex

import wx

from sat.announce import announce
from sat.util import run_in_thread

UNIT_TYPES = ["All", "Service", "Timer", "Socket", "Target", "Mount",
              "Device", "Slice", "Path"]
ACTIVE_STATES = ["All", "Active", "Inactive", "Failed"]
FILE_STATES = ["All", "Enabled", "Disabled", "Masked", "Static"]

STATUS_CMD = "systemctl status {unit} --no-pager -l"
LOGS_CMD = "journalctl -u {unit} -n 60 --no-pager -o cat"


class SystemdPanel(wx.Panel):
    def __init__(self, parent, frame):
        super().__init__(parent)
        self.frame = frame
        self._units = []  # (unit, load, active, sub, description, file_state)
        self._build_ui()
        self._bind_events()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        outer = wx.BoxSizer(wx.VERTICAL)

        filters = wx.BoxSizer(wx.HORIZONTAL)
        filters.Add(wx.StaticText(self, label="Type:"), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.type_choice = wx.Choice(self, choices=UNIT_TYPES)
        self.type_choice.SetSelection(0)
        filters.Add(self.type_choice, 0, wx.RIGHT, 12)
        filters.Add(wx.StaticText(self, label="State:"), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.state_choice = wx.Choice(self, choices=ACTIVE_STATES)
        self.state_choice.SetSelection(0)
        filters.Add(self.state_choice, 0, wx.RIGHT, 12)
        filters.Add(wx.StaticText(self, label="File:"), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.file_choice = wx.Choice(self, choices=FILE_STATES)
        self.file_choice.SetSelection(0)
        filters.Add(self.file_choice, 0, wx.RIGHT, 12)
        filters.Add(wx.StaticText(self, label="Filter:"), 0,
                    wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.filter_text = wx.TextCtrl(self)
        filters.Add(self.filter_text, 1, wx.EXPAND)
        self.refresh_btn = wx.Button(self, label="&Refresh")
        filters.Add(self.refresh_btn, 0, wx.LEFT, 12)
        outer.Add(filters, 0, wx.EXPAND | wx.ALL, 8)

        outer.Add(wx.StaticText(self, label="Units:"), 0,
                  wx.LEFT | wx.RIGHT, 8)
        self.units_list = wx.ListBox(self)
        outer.Add(self.units_list, 1, wx.EXPAND | wx.ALL, 8)

        actions = wx.WrapSizer(wx.HORIZONTAL)
        self.start_btn = wx.Button(self, label="&Start")
        self.stop_btn = wx.Button(self, label="S&top")
        self.restart_btn = wx.Button(self, label="&Restart")
        self.reload_btn = wx.Button(self, label="Re&load")
        self.enable_btn = wx.Button(self, label="&Enable")
        self.disable_btn = wx.Button(self, label="&Disable")
        self.enable_now_btn = wx.Button(self, label="Enable &now")
        self.mask_btn = wx.Button(self, label="&Mask")
        self.unmask_btn = wx.Button(self, label="&Unmask")
        self.status_btn = wx.Button(self, label="&Status")
        self.logs_btn = wx.Button(self, label="&Logs")
        self.reloadd_btn = wx.Button(self, label="Daemon &reload")
        for btn in (self.start_btn, self.stop_btn, self.restart_btn,
                    self.reload_btn, self.enable_btn, self.disable_btn,
                    self.enable_now_btn, self.mask_btn, self.unmask_btn,
                    self.status_btn, self.logs_btn, self.reloadd_btn):
            actions.Add(btn, 0, wx.RIGHT, 6)
        outer.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        outer.Add(wx.StaticText(self, label="Output:"), 0,
                  wx.LEFT | wx.RIGHT, 8)
        self.output = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY)
        outer.Add(self.output, 2, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(outer)

    def _bind_events(self):
        self.refresh_btn.Bind(wx.EVT_BUTTON, lambda e: self.refresh())
        self.type_choice.Bind(wx.EVT_CHOICE, lambda e: self._apply_filters())
        self.state_choice.Bind(wx.EVT_CHOICE, lambda e: self._apply_filters())
        self.file_choice.Bind(wx.EVT_CHOICE, lambda e: self._apply_filters())
        self.filter_text.Bind(wx.EVT_TEXT, lambda e: self._apply_filters())
        self.units_list.Bind(wx.EVT_LISTBOX, self._on_selected)

        self.start_btn.Bind(wx.EVT_BUTTON, lambda e: self._action("start"))
        self.stop_btn.Bind(wx.EVT_BUTTON, lambda e: self._action("stop"))
        self.restart_btn.Bind(wx.EVT_BUTTON, lambda e: self._action("restart"))
        self.reload_btn.Bind(wx.EVT_BUTTON, lambda e: self._action("reload"))
        self.enable_btn.Bind(wx.EVT_BUTTON, lambda e: self._action("enable"))
        self.disable_btn.Bind(wx.EVT_BUTTON, lambda e: self._action("disable"))
        self.enable_now_btn.Bind(wx.EVT_BUTTON, lambda e: self._action("enable --now"))
        self.mask_btn.Bind(wx.EVT_BUTTON, lambda e: self._action("mask"))
        self.unmask_btn.Bind(wx.EVT_BUTTON, lambda e: self._action("unmask"))
        self.status_btn.Bind(wx.EVT_BUTTON, lambda e: self._action(
            "status", use_status_cmd=True))
        self.logs_btn.Bind(wx.EVT_BUTTON, lambda e: self._action(
            "logs", use_logs_cmd=True))
        self.reloadd_btn.Bind(wx.EVT_BUTTON, lambda e: self._daemon_reload())

    # ------------------------------------------------------------- helpers

    def _set_output(self, text):
        self.output.SetValue(text or "(no output)")

    def _selected_unit(self):
        sel = self.units_list.GetSelection()
        if sel == wx.NOT_FOUND:
            announce(self, "No unit selected. Use the arrow keys to choose one.")
            return None
        return self._units[sel][0]

    # -------------------------------------------------------------- refresh

    def refresh(self):
        """Reload the unit list from the current host."""
        announce(self, "Loading systemd units...")

        def work():
            units_res = self.frame.runner.run(
                "systemctl list-units --all --no-pager --no-legend")
            files_res = self.frame.runner.run(
                "systemctl list-unit-files --no-pager --no-legend")
            return units_res, files_res

        run_in_thread(work, self._on_loaded)

    def _on_loaded(self, results):
        units_res, files_res = results
        if not units_res.ok:
            self._units = []
            self.units_list.Clear()
            self._set_output(units_res.combined or units_res.error)
            reason = units_res.error or self._first_line(units_res.stderr)
            announce(self, "Could not list systemd units. " + reason)
            return

        file_states = {}
        for line in files_res.stdout.splitlines():
            parts = shlex.split(line)
            if len(parts) >= 2:
                file_states[parts[0]] = parts[1]

        units = []
        for line in units_res.stdout.splitlines():
            parts = shlex.split(line)
            if len(parts) < 4:
                continue
            unit = parts[0]
            units.append((unit, parts[1], parts[2], parts[3],
                          " ".join(parts[4:]), file_states.get(unit, "")))
        self._units = units
        self._apply_filters(focus_list=True)

    def _first_line(self, text):
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return lines[0] if lines else ""

    def _apply_filters(self, focus_list=False):
        """Re-apply the filter choices to the loaded units."""
        utype = self.type_choice.GetStringSelection().lower()
        active = self.state_choice.GetStringSelection().lower()
        fstate = self.file_choice.GetStringSelection().lower()
        needle = self.filter_text.GetValue().strip().lower()

        shown = []
        for unit, load, act, sub, desc, fst in self._units:
            if utype != "all" and not unit.endswith("." + utype):
                continue
            if active != "all" and act != active:
                continue
            if fstate != "all" and fst != fstate:
                continue
            if needle and needle not in unit.lower() and needle not in desc.lower():
                continue
            shown.append((unit, act, sub, fst))

        labels = []
        for unit, act, sub, fst in shown:
            state = act if sub in ("", act) else f"{act} / {sub}"
            labels.append(f"{unit}, {state}, file {fst}" if fst
                          else f"{unit}, {state}")
        self.units_list.Set(labels)
        if labels:
            self.units_list.SetSelection(0)
            announce(self, f"{len(labels)} units shown. " + labels[0])
        else:
            announce(self, "No units match the current filters.")
        if focus_list:
            self.units_list.SetFocus()

    def _on_selected(self, event):
        sel = event.GetSelection()
        if 0 <= sel < self.units_list.GetCount():
            announce(self, self.units_list.GetString(sel))

    # -------------------------------------------------------------- actions

    def _action(self, verb, use_status_cmd=False, use_logs_cmd=False):
        unit = self._selected_unit()
        if not unit:
            return
        if use_status_cmd:
            command = STATUS_CMD.format(unit=unit)
            label = f"Status for {unit}"
            admin = False
        elif use_logs_cmd:
            command = LOGS_CMD.format(unit=unit)
            label = f"Logs for {unit}"
            admin = False
        else:
            command = f"systemctl {verb} {unit}"
            label = f"{verb} {unit}"
            admin = True
        self._run(command, label, admin=admin)

    def _daemon_reload(self):
        self._run("systemctl daemon-reload", "daemon reload", admin=True)

    def _run(self, command, label, admin=False):
        self._set_output(f"Running: {command}\n")
        announce(self, f"Running {label}...")

        def work():
            if admin:
                return self.frame.runner.run_admin(command, timeout=90)
            return self.frame.runner.run(command, timeout=90)

        def done(res):
            self._set_output(res.combined or res.error or "No output")
            announce(self, f"{label}: {res.summary()}")
            self.refresh()  # states changed, reload the list

        run_in_thread(work, done)

    # ------------------------------------------------------------- external

    def focus_output(self):
        self.output.SetFocus()

    def describe_state(self):
        sel = self.units_list.GetSelection()
        if 0 <= sel < self.units_list.GetCount():
            return f"Systemd, {self.units_list.GetCount()} units, selected: " + \
                self.units_list.GetString(sel)
        return "Systemd, no units loaded"
