"""The main SAT window: menus, host selector, tool notebook and status bar.

Everything is reachable from the keyboard.  Menu accelerators switch
tools (Ctrl+1..Ctrl+5), F5 refreshes the current tool, F6 reads the
output area, F8 reports the current status and F9/F10 connect or
disconnect from the selected host.
"""

import wx

from sat.announce import announce
from sat.hosts import Host, HostStore
from sat.panels.apt_panel import AptPanel
from sat.panels.docker_panel import DockerPanel
from sat.panels.hosts_panel import HostsPanel
from sat.panels.monitor_panel import MonitorPanel
from sat.panels.motd_panel import MotdPanel
from sat.panels.ports_panel import PortsPanel
from sat.panels.shell_panel import ShellPanel
from sat.panels.systemd_panel import SystemdPanel
from sat.runner import LocalRunner, SshRunner
from sat.util import run_in_thread

HELP_TEXT = """SAT — Server Administrator Tool

Keyboard shortcuts
  Ctrl+1 .. Ctrl+8   Switch tools (Systemd, Docker, MOTD, Shell, Monitor,
                     Ports, Packages, Hosts)
  F5                 Refresh the current tool
  F6                 Move to the output area of the current tool
  F8                 Report the current status aloud
  F9                 Connect to the host selected at the top
  F10                Disconnect and return to the local machine
  Ctrl+H             Manage hosts (same as the Hosts tab)
  Ctrl+Q             Quit

How SAT talks to you
  The status bar always holds the latest announcement.  Orca (Linux)
  reads it automatically; on NVDA press Insert+PageDown (desktop
  layout) to hear it.  After every action the relevant list or the
  output area receives focus, which screen readers announce.

Notes
  * The SSH connection accepts unknown host keys automatically.
  * State-changing commands use sudo automatically: over SSH the saved
    password is piped to `sudo -S` (with a plain-run fallback); locally
    passwordless `sudo -n` is tried first.  `sudo ...` typed in the
    Shell tab uses the saved password too.
  * The Monitor tab beeps and announces an alert if the server
    reboots, and can reboot or shut down the connected server.
  * Passwords are stored in plain text in ~/.sat-data.
"""


class MainFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="SAT - Server Administrator Tool",
                         size=(920, 660))
        self.runner = LocalRunner()
        self.host = Host.local_host()
        self.host_store = HostStore()
        self._choice_hosts = [Host.local_host()]
        self._build_menu()
        self._build_ui()
        self._bind_events()
        self.CreateStatusBar(1)
        self.reload_host_choices()

    # ------------------------------------------------------------------ UI

    def _build_menu(self):
        menubar = wx.MenuBar()

        file_menu = wx.Menu()
        self._menu_item(file_menu, "&Connect to selected host\tF9",
                        self._on_connect_menu)
        self._menu_item(file_menu, "&Disconnect\tF10", self._on_disconnect)
        file_menu.AppendSeparator()
        self._menu_item(file_menu, "&Manage hosts...\tCtrl+H",
                        self._on_manage_hosts)
        file_menu.AppendSeparator()
        self._menu_item(file_menu, "E&xit\tCtrl+Q", lambda e: self.Close(),
                        wx.ID_EXIT)
        menubar.Append(file_menu, "&File")

        tools_menu = wx.Menu()
        self._menu_item(tools_menu, "&Systemd\tCtrl+1",
                        lambda e: self._goto_page(0))
        self._menu_item(tools_menu, "&Docker\tCtrl+2",
                        lambda e: self._goto_page(1))
        self._menu_item(tools_menu, "&MOTD\tCtrl+3",
                        lambda e: self._goto_page(2))
        self._menu_item(tools_menu, "&Shell\tCtrl+4",
                        lambda e: self._goto_page(3))
        self._menu_item(tools_menu, "&Monitor\tCtrl+5",
                        lambda e: self._goto_page(4))
        self._menu_item(tools_menu, "&Ports\tCtrl+6",
                        lambda e: self._goto_page(5))
        self._menu_item(tools_menu, "&Packages\tCtrl+7",
                        lambda e: self._goto_page(6))
        self._menu_item(tools_menu, "&Hosts\tCtrl+8",
                        lambda e: self._goto_page(7))
        menubar.Append(tools_menu, "&Tools")

        actions_menu = wx.Menu()
        self._menu_item(actions_menu, "&Refresh current tool\tF5",
                        lambda e: self._refresh_current())
        self._menu_item(actions_menu, "&Read output\tF6",
                        lambda e: self._focus_output())
        self._menu_item(actions_menu, "&Report status\tF8",
                        lambda e: self._report_status())
        menubar.Append(actions_menu, "&Actions")

        help_menu = wx.Menu()
        self._menu_item(help_menu, "&Accessibility guide...",
                        lambda e: self._show_help())
        self._menu_item(help_menu, "&About SAT...", self._show_about,
                        wx.ID_ABOUT)
        menubar.Append(help_menu, "&Help")

        self.SetMenuBar(menubar)

    @staticmethod
    def _menu_item(menu, label, handler, item_id=wx.ID_ANY):
        """Append a menu item and bind its (auto-assigned) id."""
        item = menu.Append(item_id, label)
        menu.Bind(wx.EVT_MENU, handler, id=item.GetId())

    def _build_ui(self):
        top = wx.Panel(self)
        top_sizer = wx.BoxSizer(wx.HORIZONTAL)
        top_sizer.Add(wx.StaticText(top, label="Host:"), 0,
                      wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.host_choice = wx.Choice(top, choices=["Local machine"])
        self.host_choice.SetSelection(0)
        top_sizer.Add(self.host_choice, 1, wx.EXPAND)
        self.connect_btn = wx.Button(top, label="&Connect")
        self.disconnect_btn = wx.Button(top, label="&Disconnect")
        top_sizer.Add(self.connect_btn, 0, wx.LEFT, 12)
        top_sizer.Add(self.disconnect_btn, 0, wx.LEFT, 6)
        top.SetSizer(top_sizer)

        self.notebook = wx.Notebook(self)
        self.systemd_panel = SystemdPanel(self.notebook, self)
        self.docker_panel = DockerPanel(self.notebook, self)
        self.motd_panel = MotdPanel(self.notebook, self)
        self.shell_panel = ShellPanel(self.notebook, self)
        self.monitor_panel = MonitorPanel(self.notebook, self)
        self.ports_panel = PortsPanel(self.notebook, self)
        self.apt_panel = AptPanel(self.notebook, self)
        self.hosts_panel = HostsPanel(self.notebook, self)
        self.notebook.AddPage(self.systemd_panel, "Systemd")
        self.notebook.AddPage(self.docker_panel, "Docker")
        self.notebook.AddPage(self.motd_panel, "MOTD")
        self.notebook.AddPage(self.shell_panel, "Shell")
        self.notebook.AddPage(self.monitor_panel, "Monitor")
        self.notebook.AddPage(self.ports_panel, "Ports")
        self.notebook.AddPage(self.apt_panel, "Packages")
        self.notebook.AddPage(self.hosts_panel, "Hosts")

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(top, 0, wx.EXPAND | wx.ALL, 8)
        sizer.Add(self.notebook, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.SetSizer(sizer)

    def _bind_events(self):
        self.connect_btn.Bind(wx.EVT_BUTTON, lambda e: self._on_connect_menu())
        self.disconnect_btn.Bind(wx.EVT_BUTTON, lambda e: self._on_disconnect())
        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED,
                           self._on_page_changed)

    # ----------------------------------------------------------- host setup

    def reload_host_choices(self):
        """Rebuild the host selector from the saved host list."""
        hosts = [Host.local_host()] + list(self.host_store.hosts)
        self._choice_hosts = hosts
        self.host_choice.Set([h.name for h in hosts])
        self.host_choice.SetSelection(0)

    def _on_connect_menu(self, _event=None):
        host = self._choice_hosts[self.host_choice.GetSelection()]
        self.connect_to(host)

    def connect_to(self, host):
        """Connect to *host* in the background; on failure keep the old
        connection and explain what went wrong."""
        if host is None:
            announce(self, "No host selected.")
            return
        if host.local:
            self.runner.close()
            self.runner = LocalRunner()
            self.host = host
            self._select_host_in_choice(host)
            announce(self, "Using the local machine.")
            self._refresh_current()
            return

        self.connect_btn.Disable()
        announce(self, f"Connecting to {host.describe()}...")

        def work():
            runner = SshRunner(host)
            result = runner.run("echo SAT connected", timeout=25)
            return runner, result

        def done(pair):
            runner, result = pair
            self.connect_btn.Enable()
            if not result.ok:
                runner.close()
                announce(self, "Connection failed. " +
                         (result.error or result.combined))
                wx.MessageBox("Could not connect:\n" +
                              (result.error or result.combined),
                              "Connection failed",
                              wx.OK | wx.ICON_ERROR)
                return
            self.runner.close()
            self.runner = runner
            self.host = host
            self._select_host_in_choice(host)
            announce(self, f"Connected to {host.describe()}.")
            self._refresh_current()

        def failed(exc):
            self.connect_btn.Enable()
            announce(self, f"Connection failed. {exc}")
            wx.MessageBox(str(exc), "Connection failed",
                          wx.OK | wx.ICON_ERROR)

        run_in_thread(work, done, failed)

    def _on_disconnect(self, _event=None):
        self.runner.close()
        self.runner = LocalRunner()
        self.host = Host.local_host()
        self._select_host_in_choice(self.host)
        announce(self, "Disconnected. Using the local machine.")
        self._refresh_current()

    def _select_host_in_choice(self, host):
        for i, candidate in enumerate(self._choice_hosts):
            if candidate is host:
                self.host_choice.SetSelection(i)
                return
        self.host_choice.SetSelection(0)

    # ------------------------------------------------------------- actions

    def _goto_page(self, index):
        self.notebook.SetSelection(index)
        self.notebook.GetPage(index).SetFocus()

    def _on_page_changed(self, event):
        page = self.notebook.GetPage(event.GetSelection())
        page.refresh()

    def _current_panel(self):
        return self.notebook.GetCurrentPage()

    def _refresh_current(self):
        self._current_panel().refresh()

    def _focus_output(self):
        self._current_panel().focus_output()

    def _report_status(self):
        panel = self._current_panel()
        announce(self, f"Host: {self.runner.describe()}. {panel.describe_state()}")

    def _on_manage_hosts(self, _event=None):
        self._goto_page(7)

    def _show_help(self, _event=None):
        wx.MessageBox(HELP_TEXT, "SAT help", wx.OK | wx.ICON_INFORMATION)

    def _show_about(self, _event=None):
        from sat import __version__
        wx.MessageBox(
            f"SAT - Server Administrator Tool\nVersion {__version__}\n\n"
            "A screen-reader-friendly GUI for managing servers: systemd, "
            "Docker, MOTD, SSH shell and saved hosts.\n\n"
            "Built with wxPython and paramiko.",
            "About SAT", wx.OK | wx.ICON_INFORMATION)

    def announce(self, text):
        announce(self, text)
