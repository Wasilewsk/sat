"""Port lister: shows which TCP and UDP ports are listening on the
current host (with well-known service names) and can open a port in the
default web browser."""

import os
import re
import socket
import webbrowser

import wx

from sat.announce import announce
from sat.runner import LocalRunner, SshRunner
from sat.util import run_in_thread

WIN_NETSTAT_CMD = "netstat -an"

# Well-known port -> service name (used when the OS lookup is not
# available, e.g. for ports on a remote server).
SERVICES = {
    20: "ftp-data", 21: "ftp", 22: "ssh", 23: "telnet", 25: "smtp",
    53: "dns", 67: "dhcp", 68: "dhcp", 69: "tftp", 80: "http",
    110: "pop3", 111: "rpcbind", 123: "ntp", 137: "netbios-ns",
    138: "netbios-dgm", 139: "netbios-ssn", 143: "imap", 161: "snmp",
    179: "bgp", 389: "ldap", 443: "https", 445: "microsoft-ds",
    465: "smtps", 514: "syslog", 587: "smtp-submission", 631: "ipp",
    636: "ldaps", 873: "rsync", 993: "imaps", 995: "pop3s",
    1080: "socks", 1194: "openvpn", 1433: "mssql", 1521: "oracle",
    1723: "pptp", 2375: "docker", 2376: "docker-tls", 3000: "grafana",
    3128: "squid", 3306: "mysql", 3389: "rdp", 4369: "erlang-port",
    5000: "registry", 5432: "postgresql", 5900: "vnc", 5901: "vnc",
    6379: "redis", 8080: "http-alt", 8081: "http-alt", 8443: "https-alt",
    8888: "http-alt", 9000: "portainer", 9090: "prometheus",
    9200: "elasticsearch", 9300: "elasticsearch", 11211: "memcached",
    27017: "mongodb", 25565: "minecraft",
}

_PROC_SS_RE = re.compile(r'users:\(\("([^"]+)"')
_SS_STATES = {"listen", "unconn"}


def service_name(port, proto):
    """Return a friendly name for a well-known port, falling back to the
    local OS database."""
    if port in SERVICES:
        return SERVICES[port]
    try:
        return socket.getservbyport(port, proto)
    except (OSError, OverflowError):
        return ""


class PortsPanel(wx.Panel):
    def __init__(self, parent, frame):
        super().__init__(parent)
        self.frame = frame
        self._ports = []  # (port, proto, local_address, process)
        self._build_ui()
        self._bind_events()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        outer = wx.BoxSizer(wx.VERTICAL)

        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(self, label="Protocol:"), 0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.protocol_choice = wx.Choice(self,
                                         choices=["TCP", "UDP", "Both"])
        self.protocol_choice.SetSelection(0)
        row.Add(self.protocol_choice, 0, wx.RIGHT, 12)
        row.Add(wx.StaticText(
            self, label="Listening ports on the current host:"), 0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        self.refresh_btn = wx.Button(self, label="&Refresh")
        row.Add(self.refresh_btn, 0)
        outer.Add(row, 0, wx.EXPAND | wx.ALL, 8)

        self.ports_list = wx.ListBox(self)
        outer.Add(self.ports_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        buttons = wx.WrapSizer(wx.HORIZONTAL)
        self.open_btn = wx.Button(self, label="&Open in browser")
        self.open_port_btn = wx.Button(self, label="Open &port...")
        for btn in (self.open_btn, self.open_port_btn):
            buttons.Add(btn, 0, wx.RIGHT, 6)
        outer.Add(buttons, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)

        outer.Add(wx.StaticText(self, label="Output:"), 0,
                  wx.LEFT | wx.RIGHT | wx.TOP, 8)
        self.output = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY)
        outer.Add(self.output, 2, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(outer)

    def _bind_events(self):
        self.refresh_btn.Bind(wx.EVT_BUTTON, lambda e: self.refresh())
        self.protocol_choice.Bind(wx.EVT_CHOICE, lambda e: self.refresh())
        self.ports_list.Bind(wx.EVT_LISTBOX, self._on_selected)
        self.open_btn.Bind(wx.EVT_BUTTON, lambda e: self._open_selected())
        self.open_port_btn.Bind(wx.EVT_BUTTON, lambda e: self._open_typed())

    # -------------------------------------------------------------- refresh

    def _protocol(self):
        return self.protocol_choice.GetStringSelection()

    def _list_command(self):
        runner = self.frame.runner
        proto = self._protocol()
        if isinstance(runner, LocalRunner) and os.name == "nt":
            return WIN_NETSTAT_CMD
        if proto == "TCP":
            return "ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null"
        if proto == "UDP":
            return "ss -ulnp 2>/dev/null || netstat -ulnp 2>/dev/null"
        return ("ss -tlnp 2>/dev/null; ss -ulnp 2>/dev/null; "
                "netstat -tulpn 2>/dev/null")

    def refresh(self):
        announce(self, f"Scanning for {self._protocol()} ports...")

        def work():
            return self.frame.runner.run(self._list_command(), timeout=60)

        def done(res):
            if not res.ok:
                self._ports = []
                self.ports_list.Clear()
                self._set_output(res.combined or res.error)
                announce(self, "Could not list ports. " +
                         (res.error or self._first_line(res.stderr)))
                return
            want_udp = {"UDP": True, "TCP": False}.get(self._protocol())
            ports = self._parse(res.stdout, want_udp)
            self._ports = ports
            labels = [self._label(p, proto, local, proc)
                      for p, proto, local, proc in ports]
            self.ports_list.Set(labels)
            self._set_output("Found " + (", ".join(
                f"{p}/{proto}" for p, proto, _, _ in ports) or "none"))
            if labels:
                self.ports_list.SetSelection(0)
                announce(self, f"{len(labels)} listening ports. " + labels[0])
            else:
                announce(self, "No listening ports found.")
            self.ports_list.SetFocus()

        run_in_thread(work, done)

    # -------------------------------------------------------------- parsing

    @staticmethod
    def _label(port, proto, local, proc):
        name = service_name(port, proto)
        text = f"port {port}/{proto}"
        if name:
            text += f", {name}"
        text += f", {local}"
        if proc:
            text += f", {proc}"
        return text

    def _parse(self, text, want_udp):
        """Parse `ss`, Linux `netstat -tulpn` and Windows `netstat -an`
        output into (port, proto, local_address, process) tuples."""
        ports = []
        seen = set()
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if not parts:
                continue
            first = parts[0].lower()
            if first in _SS_STATES:
                # ss output: state is the first token; UNCONN = UDP.
                proto = "udp" if first == "unconn" else "tcp"
            elif first.startswith(("tcp", "udp")):
                # netstat output: protocol is the first token.
                proto = "udp" if first.startswith("udp") else "tcp"
                if proto == "tcp" and not any(
                        f.upper() in ("LISTEN", "LISTENING") for f in parts):
                    continue  # Windows netstat lists all TCP connections
            else:
                continue
            if want_udp is not None and (proto == "udp") != want_udp:
                continue
            # The local address is the first field containing a colon.
            local = None
            for part in parts:
                if ":" in part and not part.lower().startswith("users:"):
                    local = part
                    break
            if local is None:
                continue
            port_str = local.rpartition(":")[2]
            if not port_str.isdigit():
                continue
            port = int(port_str)
            if not (0 < port < 65536):
                continue
            proc = self._find_process(parts)
            key = (port, proto, local)
            if key in seen:
                continue
            seen.add(key)
            ports.append((port, proto, local, proc))
        ports.sort(key=lambda item: (item[0], item[1]))
        return ports

    @staticmethod
    def _find_process(parts):
        for part in parts:
            if part.startswith("users:(("):
                match = _PROC_SS_RE.search(part)
                if match:
                    return match.group(1)
            elif "/" in part and part.split("/", 1)[0].isdigit():
                return part.split("/", 1)[1]
        return ""

    # ------------------------------------------------------------ browser

    def _browse_base(self):
        runner = self.frame.runner
        if isinstance(runner, SshRunner):
            return runner.host.hostname
        return "localhost"

    def _open_selected(self):
        sel = self.ports_list.GetSelection()
        if sel == wx.NOT_FOUND:
            announce(self, "Select a port first, or use Open port...")
            return
        self._open_url(self._ports[sel][0])

    def _open_typed(self):
        value = wx.GetTextFromUser(
            "Port number to open in the browser:", "Open port",
            default_value="", parent=self).strip()
        if not value:
            return
        if not value.isdigit() or not (0 < int(value) < 65536):
            announce(self, "Please enter a valid port number.")
            return
        self._open_url(int(value))

    def _open_url(self, port):
        base = self._browse_base()
        url = f"http://{base}:{port}"
        announce(self, f"Opening {url} in the browser.")
        webbrowser.open(url)

    # ------------------------------------------------------------- helpers

    def _set_output(self, text):
        self.output.SetValue(text or "(no output)")

    def _first_line(self, text):
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return lines[0] if lines else ""

    def _on_selected(self, event):
        sel = event.GetSelection()
        if 0 <= sel < self.ports_list.GetCount():
            announce(self, self.ports_list.GetString(sel))

    # ------------------------------------------------------------- external

    def focus_output(self):
        self.output.SetFocus()

    def describe_state(self):
        return (f"Ports {self._protocol()}, "
                f"{self.ports_list.GetCount()} listening")
