"""Uptime monitor: uptime, load average, memory and disk usage on the
current host, with optional automatic refresh and a reboot alert.

Automatic refreshes update the output quietly; manual refresh announces
the summary.  If the boot time jumps back (the server rebooted) SAT
beeps and announces an alert even during quiet auto-refresh."""

import os
import re

import wx

from sat.announce import announce
from sat.runner import LocalRunner, SshRunner
from sat.util import run_in_thread

REFRESH_OPTIONS = ["Off", "10 seconds", "30 seconds", "60 seconds"]
REFRESH_MS = {"Off": 0, "10 seconds": 10000,
              "30 seconds": 30000, "60 seconds": 60000}

_UPTIME_RE = re.compile(r"up\s+(.+?),?\s+\d+\s+user")
_LOAD_RE = re.compile(r"load average:\s*(.+)")


class MonitorPanel(wx.Panel):
    def __init__(self, parent, frame):
        super().__init__(parent)
        self.frame = frame
        self._timer = wx.Timer(self)
        self._last_seconds = None
        self._last_human = None
        self._build_ui()
        self._bind_events()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        outer = wx.BoxSizer(wx.VERTICAL)

        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(self, label="Auto-refresh:"), 0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.refresh_choice = wx.Choice(self, choices=REFRESH_OPTIONS)
        self.refresh_choice.SetSelection(2)  # 30 seconds by default
        row.Add(self.refresh_choice, 0, wx.RIGHT, 12)
        self.refresh_btn = wx.Button(self, label="&Refresh now")
        row.Add(self.refresh_btn, 0)
        outer.Add(row, 0, wx.EXPAND | wx.ALL, 8)

        power = wx.BoxSizer(wx.HORIZONTAL)
        power.Add(wx.StaticText(self, label="Server power:"), 0,
                  wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.reboot_btn = wx.Button(self, label="&Reboot server")
        self.shutdown_btn = wx.Button(self, label="S&hutdown server")
        power.Add(self.reboot_btn, 0, wx.RIGHT, 6)
        power.Add(self.shutdown_btn, 0)
        outer.Add(power, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        outer.Add(wx.StaticText(
            self,
            label="Uptime, load, memory and disk on the current host:"), 0,
            wx.LEFT | wx.RIGHT, 8)
        self.output = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY)
        outer.Add(self.output, 1, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(outer)

    def _bind_events(self):
        self.refresh_btn.Bind(wx.EVT_BUTTON,
                              lambda e: self.refresh(announce_result=True))
        self.refresh_choice.Bind(wx.EVT_CHOICE, self._on_refresh_choice)
        self.reboot_btn.Bind(wx.EVT_BUTTON, lambda e: self._power("reboot"))
        self.shutdown_btn.Bind(wx.EVT_BUTTON,
                               lambda e: self._power("poweroff"))
        self.Bind(wx.EVT_TIMER, self._on_timer, self._timer)

    def _on_refresh_choice(self, event):
        ms = REFRESH_MS[self.refresh_choice.GetStringSelection()]
        if ms:
            self._timer.Start(ms)
            announce(self, f"Auto-refresh every "
                           f"{self.refresh_choice.GetStringSelection()}.")
        else:
            self._timer.Stop()
            announce(self, "Auto-refresh off.")

    def _on_timer(self, event):
        self.refresh(announce_result=False)

    # -------------------------------------------------------------- refresh

    def _monitor_commands(self):
        """(key, command) pairs for the current host type."""
        runner = self.frame.runner
        if isinstance(runner, LocalRunner) and os.name == "nt":
            return [
                ("ram", "wmic OS get FreePhysicalMemory,"
                        "TotalVisibleMemorySize /value"),
                ("disk", "wmic LogicalDisk get DeviceID,FreeSpace,Size "
                         "/value"),
            ]
        return [
            ("uptime", "uptime"),
            ("boot_seconds", "cat /proc/uptime"),
            ("ram", "free -m"),
            ("disk", "df -h /"),
        ]

    def refresh(self, announce_result=True):
        """Fetch uptime/load/memory/disk.  Automatic refreshes stay
        quiet unless the server rebooted; manual ones announce a
        summary."""
        self._update_power_buttons()
        if announce_result:
            announce(self, "Reading system status...")

        def work():
            results = []
            for key, command in self._monitor_commands():
                results.append((key, self.frame.runner.run(command,
                                                           timeout=30)))
            return results

        def done(results):
            self._render(results)
            alert = self._check_reboot(results)
            if announce_result:
                announce(self, self._build_summary(results))
            elif alert:
                announce(self, alert)
                wx.Bell()

        run_in_thread(work, done)

    # ------------------------------------------------------------ rendering

    def _render(self, results):
        blocks = []
        for key, res in results:
            if res.ok and res.combined.strip():
                blocks.append(f"[{key}]\n{res.combined}")
        self.output.SetValue("\n\n".join(blocks) or "(no readings)")

    @staticmethod
    def _first_line(text):
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return lines[0] if lines else ""

    # -------------------------------------------------------------- summary

    def _build_summary(self, results):
        parts = []
        for key, res in results:
            if not res.ok:
                continue
            if key == "uptime":
                up, load = self._parse_uptime(res.combined)
                if up:
                    parts.append(f"Uptime {up}.")
                if load:
                    parts.append(f"Load {load}.")
            elif key == "ram":
                parsed = self._parse_ram(res.combined)
                if parsed:
                    used_gb, total_gb = parsed
                    parts.append(
                        f"Memory {used_gb:.1f} of {total_gb:.1f} "
                        f"gigabytes used.")
            elif key == "disk":
                parsed = self._parse_disk(res.combined)
                if parsed:
                    parts.append(f"Disk {parsed}.")
        return " ".join(parts) or "No readings available."

    @staticmethod
    def _parse_uptime(text):
        line = MonitorPanel._first_line(text)
        m = _UPTIME_RE.search(line)
        m2 = _LOAD_RE.search(line)
        return (m.group(1) if m else "", m2.group(1) if m2 else "")

    @staticmethod
    def _parse_ram(text):
        """Linux `free -m` or Windows `wmic OS` output -> (used_gb,
        total_gb) or None."""
        kvs = {}
        for line in text.splitlines():
            line = line.strip()
            if "=" in line:
                key, value = line.split("=", 1)
                kvs[key.strip()] = value.strip()
        if "TotalVisibleMemorySize" in kvs:
            try:
                total_kb = int(kvs["TotalVisibleMemorySize"])
                free_kb = int(kvs.get("FreePhysicalMemory", 0))
                return (total_kb - free_kb) / 1024 / 1024, total_kb / 1024 / 1024
            except ValueError:
                return None
        for line in text.splitlines():
            parts = line.split()
            if parts and parts[0].startswith("Mem:") and len(parts) >= 3:
                try:
                    return int(parts[2]) / 1024, int(parts[1]) / 1024
                except ValueError:
                    return None
        return None

    @staticmethod
    def _parse_disk(text):
        """Linux `df -h /` or Windows `wmic LogicalDisk` output -> a
        short spoken summary string or None."""
        drives = {}
        current = None
        for line in text.splitlines():
            line = line.strip()
            if not line:
                current = None
                continue
            if line.startswith("DeviceID="):
                current = line.split("=", 1)[1].strip()
                drives.setdefault(current, {})
            elif "=" in line and current is not None:
                key, value = line.split("=", 1)
                drives[current][key.strip()] = value.strip()
        if drives:
            parts = []
            for dev, info in drives.items():
                try:
                    free_gb = int(info["FreeSpace"]) / 1024 ** 3
                    size_gb = int(info["Size"]) / 1024 ** 3
                    parts.append(
                        f"{dev} {free_gb:.1f} of {size_gb:.1f} gigabytes free")
                except (KeyError, ValueError):
                    continue
            if parts:
                return ". ".join(parts)
        for line in text.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 6 and parts[0].startswith("/"):
                return f"root filesystem {parts[4]} used"
        return None

    # ---------------------------------------------------------- reboot alert

    def _extract_boot_seconds(self, results):
        for key, res in results:
            if key != "boot_seconds" or not res.ok:
                continue
            try:
                return float(res.combined.split()[0])
            except (ValueError, IndexError):
                return None
        return None

    def _check_reboot(self, results):
        seconds = self._extract_boot_seconds(results)
        if seconds is None:
            return None
        if (self._last_seconds is not None
                and seconds < self._last_seconds - 120):
            old = self._last_human or f"{self._last_seconds:.0f} seconds"
            new = self._human(seconds)
            self._last_seconds = seconds
            self._last_human = new
            return (f"Attention: the server has rebooted. Previous uptime "
                    f"was {old}, now {new}.")
        self._last_seconds = seconds
        self._last_human = self._human(seconds)
        return None

    # ---------------------------------------------------------- server power

    def _update_power_buttons(self):
        """Reboot/shutdown only make sense on a connected server, never
        on the local workstation."""
        connected = isinstance(self.frame.runner, SshRunner)
        self.reboot_btn.Enable(connected)
        self.shutdown_btn.Enable(connected)

    def _power(self, action):
        runner = self.frame.runner
        if not isinstance(runner, SshRunner):
            announce(self, "Reboot and shutdown only work on a connected "
                           "server, not the local machine.")
            return
        verb = "Reboot" if action == "reboot" else "Shut down"
        if wx.MessageBox(
                f"{verb} the server {runner.describe()}? This disconnects "
                "SAT and interrupts running services.",
                f"Confirm {verb.lower()}",
                wx.YES_NO | wx.ICON_WARNING) != wx.YES:
            return
        flag = "-r" if action == "reboot" else "-h"
        command = f"systemctl {action} 2>/dev/null || shutdown {flag} now"
        announce(self, f"{verb}ing the server...")

        def work():
            return runner.run_admin(command, timeout=60)

        def done(res):
            if res.ok:
                announce(self, f"{verb} command completed.")
                return
            low = (res.error or res.combined).lower()
            if "timed out" in low or "closed" in low or "reset" in low:
                # The machine went down before answering; expected.
                announce(self, f"{verb} command sent. The connection "
                               "dropped, as expected.")
            else:
                announce(self, f"{verb} failed: "
                               f"{res.error or res.combined}")

        run_in_thread(work, done)

    @staticmethod
    def _human(seconds):
        days, rem = divmod(int(seconds), 86400)
        hours, rem = divmod(rem, 3600)
        minutes = rem // 60
        bits = []
        if days:
            bits.append(f"{days} days")
        if hours:
            bits.append(f"{hours} hours")
        if minutes:
            bits.append(f"{minutes} minutes")
        return ", ".join(bits) or "under a minute"

    # ------------------------------------------------------------- external

    def focus_output(self):
        self.output.SetFocus()

    def describe_state(self):
        lines = [ln for ln in self.output.GetValue().splitlines() if ln.strip()]
        if lines:
            return f"Monitor, {lines[0]}"
        return "Monitor, no readings yet"
