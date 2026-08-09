"""Smoke test: builds the SAT window and exercises every panel without
opening a real connection.  Useful to verify the app starts cleanly.

Run with: python smoke_test.py
"""

import sys
import tempfile
import time

import wx


def pump(app, seconds=1.5):
    """Let background threads and wx.CallAfter callbacks settle."""
    end = time.time() + seconds
    while time.time() < end:
        time.sleep(0.05)
        app.Yield()


def main():
    app = wx.App(redirect=False)

    # Keep test data out of the real config directory.
    import sat.hosts as hosts_mod
    hosts_mod.config_dir = lambda: tempfile.mkdtemp(prefix="sat-test-")

    from sat.main_frame import MainFrame
    from sat.panels.hosts_panel import HostDialog
    from sat.panels.ports_panel import PortsPanel
    from sat.runner import LocalRunner

    frame = MainFrame()
    frame.reload_host_choices()

    assert frame.runner.describe() == "Local machine"
    assert frame.host_store is not None
    assert frame.notebook.GetPageCount() == 8

    # Switch through every tab; on this machine systemctl/docker/apt
    # do not exist, which exercises the graceful-failure paths.
    for i in range(8):
        frame._goto_page(i)
        pump(app)

    # Report status writes to the status bar.
    frame._report_status()
    assert frame.GetStatusBar().GetStatusText() != ""

    # Port parser handles ss, Linux netstat and Windows netstat output,
    # TCP and UDP, with service names.
    panel = PortsPanel(frame, frame)
    ss_out = (
        "State    Recv-Q   Send-Q   Local Address:Port   Peer Address:Port   Process\n"
        "LISTEN   0        4096     0.0.0.0:22           0.0.0.0:*           "
        'users:(("sshd",pid=123,fd=3))\n'
        "LISTEN   0        128      [::]:80               [::]:*              "
        'users:(("nginx",pid=456,fd=6))\n'
        "UNCONN   0        0        0.0.0.0:53            0.0.0.0:*           "
        'users:(("systemd-resolve",pid=9,fd=1))\n')
    linux_netstat = (
        "Proto Recv-Q Send-Q Local Address Foreign Address State       PID/Program name\n"
        "tcp        0      0 0.0.0.0:443     0.0.0.0:*               LISTEN      789/nginx\n"
        "udp        0      0 0.0.0.0:123     0.0.0.0:*                          1234/chronyd\n")
    win_netstat = (
        "\n  TCP    0.0.0.0:135            0.0.0.0:0                LISTENING\n"
        "  TCP    [::]:445              [::]:0                 LISTENING\n"
        "  UDP    0.0.0.0:123            *:*                                     \n")
    parsed = panel._parse(ss_out, False)
    assert (22, "tcp", "0.0.0.0:22", "sshd") in parsed, parsed
    assert (80, "tcp", "[::]:80", "nginx") in parsed, parsed
    assert not any(p == 53 for p, _, _, _ in parsed), parsed
    parsed = panel._parse(ss_out, True)
    assert (53, "udp", "0.0.0.0:53", "systemd-resolve") in parsed, parsed
    parsed = panel._parse(linux_netstat, None)
    assert (443, "tcp", "0.0.0.0:443", "nginx") in parsed, parsed
    assert (123, "udp", "0.0.0.0:123", "chronyd") in parsed, parsed
    parsed = panel._parse(win_netstat, False)
    assert (135, "tcp", "0.0.0.0:135", "") in parsed, parsed
    assert (445, "tcp", "[::]:445", "") in parsed, parsed
    assert not any(p == 123 for p, _, _, _ in parsed), parsed
    assert panel._label(22, "tcp", "0.0.0.0:22", "sshd").startswith("port 22/tcp, ssh")
    panel.Destroy()

    # Monitor summary parsing (Linux free/df/uptime + Windows wmic).
    from sat.panels.monitor_panel import MonitorPanel
    mon = MonitorPanel(frame, frame)
    assert mon._parse_ram("Mem:       3903      1245      1987        62        328       1") == (1245 / 1024, 3903 / 1024)
    assert mon._parse_ram("TotalVisibleMemorySize=16777216\nFreePhysicalMemory=8388608") == (8388608 / 1024 / 1024, 16777216 / 1024 / 1024)
    assert "48%" in mon._parse_disk("Filesystem Size Used Avail Use% Mounted on\n/dev/sda1 20G 9.0G 9.8G 48% /")
    assert "C:" in mon._parse_disk("DeviceID=C:\nFreeSpace=45000000000\nSize=128000000000")
    assert mon._parse_uptime(" 12:00:01 up 3 days,  2 users,  load average: 0.10, 0.08, 0.05")[0] == "3 days"
    assert mon._human(90061) == "1 days, 1 hours, 1 minutes"
    fake = lambda seconds: [("boot_seconds", type("R", (), {"ok": True, "combined": str(seconds)})())]
    assert mon._check_reboot(fake(259200)) is None  # 3 days, baseline
    reboot = mon._check_reboot(fake(50))
    assert reboot and "rebooted" in reboot, reboot
    # Reboot/shutdown are disabled on the local machine.
    mon._update_power_buttons()
    assert not mon.reboot_btn.IsEnabled()
    assert not mon.shutdown_btn.IsEnabled()
    mon.Destroy()

    # Shell detects bare-sudo no-tty errors for the retry path.
    from sat.panels.shell_panel import ShellPanel
    assert ShellPanel._looks_like_sudo_issue(
        "sudo: a terminal is required to read the password; "
        "either use the -S option to read from standard input "
        "or configure an askpass helper\nsudo: a password is required")
    assert not ShellPanel._looks_like_sudo_issue("permission denied")

    # Apt search/list parsing.
    from sat.panels.apt_panel import AptPanel
    apt = AptPanel(frame, frame)
    parsed = apt._parse(
        "Sorting... Done\n"
        "Full Text Search... Done\n"
        "nginx/stable,stable-security,now 1.24.0-1+deb12u2 amd64 "
        "[installed,automatic]\n"
        "  high performance web server\n"
        "python3/stable 3.11.2-1 amd64\n"
        "  interactive high-level object-oriented language\n")
    assert [name for name, _ in parsed] == ["nginx", "python3"], parsed
    assert parsed[0][1].startswith("nginx, 1.24.0"), parsed
    assert len(parsed[0][1]) < 200  # description line not merged in
    apt.Destroy()

    # Docker create-container dialog builds a correct command.
    from sat.panels.docker_panel import DockerCreateDialog
    dlg = DockerCreateDialog(frame)
    dlg.image_text.SetValue("nginx:latest")
    dlg.name_text.SetValue("web")
    dlg.ports_text.SetValue("8080:80, 443:443")
    dlg.volumes_text.SetValue("/data:/data")
    dlg.env_text.SetValue("FOO=bar")
    dlg.restart_choice.SetSelection(1)
    dlg.command_text.SetValue("-g 'daemon off;'")
    cmd = dlg.command()
    assert cmd.startswith("docker run -d"), cmd
    for token in ("--name", "web", "-p", "8080:80", "-p", "443:443",
                  "-v", "/data:/data", "-e", "FOO=bar", "--restart",
                  "always", "nginx:latest", "-g", "daemon off;"):
        assert token in cmd, (token, cmd)
    dlg.Destroy()

    # Host dialog builds with defaults.
    dlg = HostDialog(frame)
    assert dlg.port_text.GetValue() == "22"
    dlg.Destroy()

    # Host store round-trip.
    store = frame.host_store
    from sat.hosts import Host
    store.hosts.append(Host(name="test", hostname="example.com",
                            username="root"))
    store.save()
    store2 = frame.host_store.__class__(store.path)
    assert store2.hosts[-1].hostname == "example.com"
    store.hosts.pop()
    store.save()

    # Local runner works, including the admin fallback (no sudo on
    # Windows, so it runs plainly).
    res = LocalRunner().run("echo hello")
    assert res.ok and "hello" in res.stdout, res.combined
    res = LocalRunner().run_admin("echo admin")
    assert res.ok and "admin" in res.stdout, res.combined

    frame.Destroy()
    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
