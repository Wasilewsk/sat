"""Manage the list of saved servers: add, edit, delete and connect."""

import wx

from sat.announce import announce
from sat.hosts import Host
from sat.runner import SshRunner
from sat.util import run_in_thread


class HostDialog(wx.Dialog):
    """Add or edit one host definition."""

    def __init__(self, parent, host=None):
        title = "Edit host" if host else "Add host"
        super().__init__(parent, title=title, size=(460, 360))
        self._host = host or Host()

        grid = wx.GridBagSizer(8, 8)
        row = 0

        self.name_text = self._field(grid, row, "Name:", self._host.name)
        grid.AddGrowableCol(1)
        row += 1
        self.hostname_text = self._field(grid, row, "Hostname or IP:",
                                         self._host.hostname)
        row += 1
        self.port_text = self._field(grid, row, "SSH port:",
                                     str(self._host.port or 22))
        row += 1
        self.user_text = self._field(grid, row, "Username:",
                                     self._host.username)
        row += 1
        self.password_text = self._field(
            grid, row, "Password (optional):", self._host.password)
        self.password_text.SetWindowStyle(wx.TE_PASSWORD)
        row += 1
        self.keyfile_text = self._field(grid, row, "SSH key file:",
                                        self._host.keyfile)
        browse = wx.Button(self, label="B&rowse...")
        grid.Add(browse, (row, 2))
        browse.Bind(wx.EVT_BUTTON, self._on_browse)

        self.test_label = wx.StaticText(self, label="")
        self.test_btn = wx.Button(self, label="&Test connection")
        self.test_btn.Bind(wx.EVT_BUTTON, self._on_test)
        grid.Add(self.test_label, (row + 1, 0), span=(1, 2))
        grid.Add(self.test_btn, (row + 1, 2))

        btns = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(grid, 1, wx.EXPAND | wx.ALL, 12)
        sizer.Add(btns, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(sizer)
        self.name_text.SetFocus()

    def _field(self, grid, row, label, value):
        grid.Add(wx.StaticText(self, label=label), (row, 0),
                 flag=wx.ALIGN_CENTER_VERTICAL)
        ctrl = wx.TextCtrl(self, value=value)
        grid.Add(ctrl, (row, 1), flag=wx.EXPAND)
        return ctrl

    def _on_browse(self, event):
        with wx.FileDialog(self, "Choose SSH private key file",
                           style=wx.FD_OPEN) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.keyfile_text.SetValue(dlg.GetPath())

    def _make_host(self):
        name = self.name_text.GetValue().strip()
        hostname = self.hostname_text.GetValue().strip()
        try:
            port = int(self.port_text.GetValue().strip() or 22)
        except ValueError:
            port = 22
        return Host(name=name, hostname=hostname, port=port,
                    username=self.user_text.GetValue().strip(),
                    password=self.password_text.GetValue(),
                    keyfile=self.keyfile_text.GetValue().strip())

    def _on_test(self, event):
        host = self._make_host()
        if not host.hostname:
            self.test_label.SetLabel("Enter a hostname first.")
            return
        self.test_btn.Disable()
        self.test_label.SetLabel("Testing...")

        def work():
            runner = SshRunner(host)
            return runner.run("echo SAT connection test ok", timeout=20)

        def done(res):
            self.test_btn.Enable()
            if res.ok:
                self.test_label.SetLabel("Connection succeeded.")
            else:
                self.test_label.SetLabel(
                    "Connection failed: " + (res.error or res.combined))

        def failed(exc):
            self.test_btn.Enable()
            self.test_label.SetLabel(f"Connection failed: {exc}")

        run_in_thread(work, done, failed)

    def _on_ok(self, event):
        host = self._make_host()
        if not host.name:
            wx.MessageBox("Please enter a name for this host.",
                          "Missing name", wx.OK | wx.ICON_INFORMATION)
            return
        if not host.hostname:
            wx.MessageBox("Please enter a hostname or IP address.",
                          "Missing hostname", wx.OK | wx.ICON_INFORMATION)
            return
        self._result = host
        self.EndModal(wx.ID_OK)

    def get_host(self):
        return getattr(self, "_result", None)


class HostsPanel(wx.Panel):
    def __init__(self, parent, frame):
        super().__init__(parent)
        self.frame = frame
        self._build_ui()
        self._bind_events()
        self.refresh()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        outer = wx.BoxSizer(wx.VERTICAL)

        outer.Add(wx.StaticText(
            self,
            label="Saved servers. Select one and press Connect, or add a "
                  "new one. The first entry, Local machine, is always "
                  "available."), 0, wx.ALL, 8)

        self.hosts_list = wx.ListBox(self)
        outer.Add(self.hosts_list, 1, wx.EXPAND | wx.ALL, 8)

        buttons = wx.WrapSizer(wx.HORIZONTAL)
        self.add_btn = wx.Button(self, label="&Add...")
        self.edit_btn = wx.Button(self, label="&Edit...")
        self.delete_btn = wx.Button(self, label="&Delete")
        self.connect_btn = wx.Button(self, label="&Connect")
        for btn in (self.add_btn, self.edit_btn, self.delete_btn,
                    self.connect_btn):
            buttons.Add(btn, 0, wx.RIGHT, 6)
        outer.Add(buttons, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        outer.Add(wx.StaticText(self, label="Output:"), 0,
                  wx.LEFT | wx.RIGHT, 8)
        self.output = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY)
        outer.Add(self.output, 2, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(outer)

    def _bind_events(self):
        self.hosts_list.Bind(wx.EVT_LISTBOX, self._on_selected)
        self.hosts_list.Bind(wx.EVT_LISTBOX_DCLICK,
                             lambda e: self.frame.connect_to(self._selected_host()))
        self.add_btn.Bind(wx.EVT_BUTTON, self._on_add)
        self.edit_btn.Bind(wx.EVT_BUTTON, self._on_edit)
        self.delete_btn.Bind(wx.EVT_BUTTON, self._on_delete)
        self.connect_btn.Bind(wx.EVT_BUTTON, self._on_connect)

    # -------------------------------------------------------------- refresh

    def refresh(self):
        hosts = self.frame.host_store.hosts
        labels = [h.describe() for h in hosts]
        self.hosts_list.Set(labels)
        if labels:
            self.hosts_list.SetSelection(0)
        announce(self, f"{len(labels)} saved hosts.")

    def _selected_host(self):
        sel = self.hosts_list.GetSelection()
        if sel == wx.NOT_FOUND:
            return None
        return self.frame.host_store.hosts[sel]

    def _on_selected(self, event):
        sel = event.GetSelection()
        if 0 <= sel < self.hosts_list.GetCount():
            announce(self, self.hosts_list.GetString(sel))

    # -------------------------------------------------------------- actions

    def _on_add(self, event):
        dlg = HostDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            host = dlg.get_host()
            if host:
                self.frame.host_store.hosts.append(host)
                self.frame.host_store.save()
                self.frame.reload_host_choices()
                self.refresh()
                announce(self, f"Added host {host.describe()}.")
        dlg.Destroy()

    def _on_edit(self, event):
        host = self._selected_host()
        if host is None:
            announce(self, "Select a host to edit.")
            return
        dlg = HostDialog(self, host)
        if dlg.ShowModal() == wx.ID_OK:
            edited = dlg.get_host()
            if edited:
                idx = self.frame.host_store.hosts.index(host)
                self.frame.host_store.hosts[idx] = edited
                self.frame.host_store.save()
                self.frame.reload_host_choices()
                self.refresh()
                announce(self, f"Updated host {edited.describe()}.")
        dlg.Destroy()

    def _on_delete(self, event):
        host = self._selected_host()
        if host is None:
            announce(self, "Select a host to delete.")
            return
        if wx.MessageBox(f"Delete host {host.describe()}?",
                         "Confirm delete",
                         wx.YES_NO | wx.ICON_WARNING) != wx.YES:
            return
        self.frame.host_store.hosts.remove(host)
        self.frame.host_store.save()
        self.frame.reload_host_choices()
        self.refresh()
        announce(self, f"Deleted host {host.name}.")

    def _on_connect(self, event):
        host = self._selected_host()
        if host is None:
            announce(self, "Select a host to connect to.")
            return
        self.frame.connect_to(host)

    # ------------------------------------------------------------- external

    def focus_output(self):
        self.output.SetFocus()

    def describe_state(self):
        return f"Hosts, {self.hosts_list.GetCount()} saved"
