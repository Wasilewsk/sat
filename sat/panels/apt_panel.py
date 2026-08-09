"""APT package management for Debian/Ubuntu hosts: search, install,
remove, purge, show, update, upgrade, full-upgrade, autoremove and
clean."""

import shlex

import wx

from sat.announce import announce
from sat.util import run_in_thread

MODES = ["Search", "Installed", "Upgradable"]
NONINTERACTIVE = "DEBIAN_FRONTEND=noninteractive"


class AptPanel(wx.Panel):
    def __init__(self, parent, frame):
        super().__init__(parent)
        self.frame = frame
        self._packages = []  # (name, label)
        self._build_ui()
        self._bind_events()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        outer = wx.BoxSizer(wx.VERTICAL)

        top = wx.BoxSizer(wx.HORIZONTAL)
        top.Add(wx.StaticText(self, label="Mode:"), 0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.mode_choice = wx.Choice(self, choices=MODES)
        self.mode_choice.SetSelection(0)
        top.Add(self.mode_choice, 0, wx.RIGHT, 12)
        top.Add(wx.StaticText(self, label="Query:"), 0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.query_text = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        top.Add(self.query_text, 1, wx.EXPAND)
        self.search_btn = wx.Button(self, label="&Search")
        top.Add(self.search_btn, 0, wx.LEFT, 12)
        outer.Add(top, 0, wx.EXPAND | wx.ALL, 8)

        outer.Add(wx.StaticText(self, label="Packages:"), 0,
                  wx.LEFT | wx.RIGHT, 8)
        self.items_list = wx.ListBox(self)
        outer.Add(self.items_list, 1, wx.EXPAND | wx.ALL, 8)

        actions = wx.WrapSizer(wx.HORIZONTAL)
        self.install_btn = wx.Button(self, label="&Install")
        self.remove_btn = wx.Button(self, label="&Remove")
        self.purge_btn = wx.Button(self, label="&Purge")
        self.show_btn = wx.Button(self, label="S&how")
        self.update_btn = wx.Button(self, label="Update &lists")
        self.upgrade_btn = wx.Button(self, label="&Upgrade")
        self.full_upgrade_btn = wx.Button(self, label="&Full upgrade")
        self.autoremove_btn = wx.Button(self, label="&Autoremove")
        self.clean_btn = wx.Button(self, label="&Clean")
        for btn in (self.install_btn, self.remove_btn, self.purge_btn,
                    self.show_btn, self.update_btn, self.upgrade_btn,
                    self.full_upgrade_btn, self.autoremove_btn,
                    self.clean_btn):
            actions.Add(btn, 0, wx.RIGHT, 6)
        outer.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        outer.Add(wx.StaticText(self, label="Output:"), 0,
                  wx.LEFT | wx.RIGHT, 8)
        self.output = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY)
        outer.Add(self.output, 2, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(outer)

    def _bind_events(self):
        self.search_btn.Bind(wx.EVT_BUTTON, lambda e: self._run_list())
        self.query_text.Bind(wx.EVT_TEXT_ENTER, lambda e: self._run_list())
        self.items_list.Bind(wx.EVT_LISTBOX, self._on_selected)
        self.install_btn.Bind(wx.EVT_BUTTON, lambda e: self._install())
        self.remove_btn.Bind(wx.EVT_BUTTON, lambda e: self._remove(purge=False))
        self.purge_btn.Bind(wx.EVT_BUTTON, lambda e: self._remove(purge=True))
        self.show_btn.Bind(wx.EVT_BUTTON, lambda e: self._show())
        self.update_btn.Bind(wx.EVT_BUTTON, lambda e: self._update())
        self.upgrade_btn.Bind(wx.EVT_BUTTON, lambda e: self._upgrade(full=False))
        self.full_upgrade_btn.Bind(wx.EVT_BUTTON, lambda e: self._upgrade(full=True))
        self.autoremove_btn.Bind(wx.EVT_BUTTON, lambda e: self._autoremove())
        self.clean_btn.Bind(wx.EVT_BUTTON, lambda e: self._clean())

    # ------------------------------------------------------------- helpers

    def _set_output(self, text):
        self.output.SetValue(text or "(no output)")

    def _selected_name(self):
        sel = self.items_list.GetSelection()
        if sel == wx.NOT_FOUND:
            announce(self, "Select a package first.")
            return None
        return self._packages[sel][0]

    @staticmethod
    def _confirm(message):
        return wx.MessageBox(message, "Confirm",
                             wx.YES_NO | wx.ICON_QUESTION) == wx.YES

    # -------------------------------------------------------------- search

    def refresh(self):
        self._run_list()

    def _run_list(self):
        mode = self.mode_choice.GetStringSelection()
        query = self.query_text.GetValue().strip()
        if mode == "Search":
            if not query:
                announce(self, "Type a search term first.")
                self.query_text.SetFocus()
                return
            command = "apt search " + shlex.quote(query)
            label = f"search for {query}"
        elif mode == "Installed":
            command = "apt list --installed"
            label = "installed packages"
        else:
            command = "apt list --upgradable"
            label = "packages with updates"
        announce(self, f"Running {label}...")

        def work():
            return self.frame.runner.run(command, timeout=120)

        def done(res):
            if not res.ok:
                self._packages = []
                self.items_list.Clear()
                self._set_output(res.combined or res.error)
                announce(self, "Could not list packages. " +
                         (res.error or self._first_line(res.stderr)))
                return
            packages = self._parse(res.stdout)
            self._packages = packages
            self.items_list.Set([label for _, label in packages])
            if packages:
                self.items_list.SetSelection(0)
                announce(self, f"{len(packages)} packages. " + packages[0][1])
            else:
                announce(self, "No packages found.")
            self.items_list.SetFocus()

        run_in_thread(work, done)

    @staticmethod
    def _parse(text):
        """Parse `apt search` / `apt list` output into (name, label)
        tuples.  Name lines start with `<name>/<release>`; description
        and header lines are skipped."""
        packages = []
        for line in text.splitlines():
            if line.startswith("  ") or not line.strip():
                continue
            first = line.split()[0]
            if "/" not in first:
                continue
            name = first.split("/", 1)[0]
            rest = line[len(first):].strip()
            packages.append((name, f"{name}, {rest}" if rest else name))
        return packages

    # -------------------------------------------------------------- actions

    def _install(self):
        name = self._selected_name()
        if not name:
            return
        if not self._confirm(f"Install {name}? This downloads and "
                             f"installs the package on "
                             f"{self.frame.runner.describe()}."):
            return
        self._run(f"{NONINTERACTIVE} apt install -y {name}",
                  f"install {name}", admin=True, timeout=600)

    def _remove(self, purge=False):
        name = self._selected_name()
        if not name:
            return
        verb = "purge" if purge else "remove"
        note = " This also deletes configuration files." if purge else ""
        if not self._confirm(f"{verb.capitalize()} {name}?{note}"):
            return
        self._run(f"{NONINTERACTIVE} apt {verb} -y {name}",
                  f"{verb} {name}", admin=True, timeout=600)

    def _show(self):
        name = self._selected_name()
        if not name:
            return
        self._run(f"apt show {name}", f"show {name}", admin=False)

    def _update(self):
        self._run("apt update", "update package lists", admin=True,
                  timeout=600)

    def _upgrade(self, full=False):
        verb = "full-upgrade" if full else "upgrade"
        what = "a full upgrade (may remove or add packages)" if full \
            else "an upgrade of all installed packages"
        if not self._confirm(f"Run apt {verb}? This performs {what}."):
            return
        self._run(f"{NONINTERACTIVE} apt {verb} -y", f"apt {verb}",
                  admin=True, timeout=900)

    def _autoremove(self):
        if not self._confirm("Autoremove removes unused packages that "
                             "were installed automatically. Continue?"):
            return
        self._run(f"{NONINTERACTIVE} apt autoremove -y", "autoremove",
                  admin=True, timeout=600)

    def _clean(self):
        if not self._confirm("Clean deletes downloaded package files "
                             "from the cache. Continue?"):
            return
        self._run("apt clean", "clean package cache", admin=True)

    def _run(self, command, label, admin=False, timeout=120):
        self._set_output(f"Running: {command}\n")
        announce(self, f"Running {label}...")

        def work():
            if admin:
                return self.frame.runner.run_admin(command, timeout=timeout)
            return self.frame.runner.run(command, timeout=timeout)

        def done(res):
            self._set_output(res.combined or res.error or "No output")
            announce(self, f"{label}: {res.summary()}")
            self._run_list()  # the package set changed, refresh the list

        run_in_thread(work, done)

    # ------------------------------------------------------------- helpers

    def _first_line(self, text):
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return lines[0] if lines else ""

    def _on_selected(self, event):
        sel = event.GetSelection()
        if 0 <= sel < self.items_list.GetCount():
            announce(self, self.items_list.GetString(sel))

    # ------------------------------------------------------------- external

    def focus_output(self):
        self.output.SetFocus()

    def describe_state(self):
        mode = self.mode_choice.GetStringSelection().lower()
        return f"Packages ({mode}), {self.items_list.GetCount()} listed"
