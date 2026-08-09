# SAT - Server Administrator Tool

SAT is a screen-reader-friendly desktop GUI for managing servers.  One
window does it all: systemd units, Docker, the message of the day,
saved SSH hosts and a command shell - on your local machine or on any
server you connect to over SSH.

Built with Python, [wxPython](https://wxpython.org) and
[paramiko](https://paramiko.org).

## Features

- **Hosts** - save server definitions (hostname, port, user, password or
  SSH key), test the connection, connect and disconnect.  Everything
  runs on the local machine until you connect to a server; then the
  same tools operate on that server over SSH.
- **Systemd** - list all units, filter by type/state/name, then start,
  stop, restart, reload, enable, disable, mask, unmask, view status and
  journal logs, or reload the daemon.
- **Docker** - browse containers, images and volumes; start, stop,
  restart, pause, unpause, remove, pull images, create volumes and
  **create containers** (image, name, port mappings, volume mounts,
  environment variables, restart policy and command), inspect, view
  logs and prune unused data.
- **MOTD** - read, edit and save `/etc/motd` (or any path), with an
  automatic `.bak` backup on every save and one-key restore.
- **Monitor** - uptime, load average, **memory and disk usage** on the
  current host, with automatic refresh every 10/30/60 seconds (updates
  quietly, no spoken spam).  If the server **reboots**, SAT beeps and
  announces an alert even during quiet auto-refresh.
- **Ports** - list every listening **TCP and UDP** port (works with `ss`
  on Linux servers, `netstat` on Windows), with **well-known service
  names** and the owning process where available, and open a port in
  your default browser - either the selected one or a typed port
  number.  On a connected server the browser opens
  `http://<server>:<port>`.
- **Packages (APT)** - full apt toolset for Debian/Ubuntu hosts:
  **search** by name/description, list **installed** and
  **upgradable** packages, **install**, **remove** and **purge**
  (with confirmation), **show** package details, **update** the package
  lists, **upgrade** or **full-upgrade** all packages,
  **autoremove** and **clean**.  Package-changing operations run with
  sudo automatically.
- **Shell** - a line-based command prompt on the current host.  Type a
  command, press Enter, arrow through the plain-text output.  Works
  locally and over SSH, and is far easier to use with a screen reader
  than a terminal emulator.

## Install and run

```bash
pip install -r requirements.txt
python -m sat
```

or simply `python run_sat.py`.  On Windows, `python run_sat.pyw`-style
launching can be used to avoid a console window.

Needs Python 3.8+ (tested with 3.12, wxPython 4.2, paramiko 5).

## Using SAT with a screen reader

SAT is designed to be driven entirely from the keyboard.

| Key | Action |
| --- | --- |
| `Ctrl+1` .. `Ctrl+8` | Switch tools: Systemd, Docker, MOTD, Shell, Monitor, Ports, Packages, Hosts |
| `F5` | Refresh the current tool |
| `F6` | Jump to the output area of the current tool |
| `F8` | Report current status (host + selection) aloud |
| `F9` | Connect to the host selected at the top |
| `F10` | Disconnect and go back to the local machine |
| `Ctrl+H` | Open the Hosts tab |
| `Ctrl+Q` | Quit |

How SAT talks to you:

- The **status bar always holds the latest announcement**.  Orca on
  Linux reads it automatically; with NVDA press `Insert+PageDown`
  (desktop layout) to hear it at any moment.
- After every action, focus moves to the thing that changed: the unit
  or container list, or the output pane.  Screen readers announce the
  focused item, so you always get spoken feedback.
- Every button has a mnemonic (`&Start` means `Alt+S` while the panel
  has focus), every list is a plain list box you can arrow through, and
  all output is plain text you can read line by line.
- Select a list item with the arrow keys to hear it described; press
  `Enter` on a button to run it.

The Help menu contains an accessibility guide with these shortcuts.

## How the pieces fit together

```
sat/
  app.py            wx.App and entry point
  main_frame.py     the main window: menus, host selector, notebook
  announce.py       status-bar + accessibility announcements
  hosts.py          saved host definitions (JSON in ~/.sat-data)
  runner.py         LocalRunner (subprocess) and SshRunner (paramiko)
  util.py           worker-thread helper so the UI never blocks
  panels/
    systemd_panel.py  systemctl unit management
    docker_panel.py   docker containers, images, volumes
    apt_panel.py      apt search/install/remove/upgrade tool
    motd_panel.py     /etc/motd editor with backups
    monitor_panel.py  uptime/load/memory/disk monitor with auto-refresh
    ports_panel.py    listening-port lister + open in browser
    shell_panel.py    line-based command shell
    hosts_panel.py    add/edit/delete/connect to saved servers
```

Every panel talks to a `Runner`, so the same actions work locally and
over SSH.  `smoke_test.py` builds the whole window and exercises every
panel without a server; run it with `python smoke_test.py`.

## Privileged commands and sudo

State-changing systemd commands, Docker commands and MOTD writes may
need root.  SAT handles this automatically:

- **Over SSH**: the password saved for the host is fed to
  `sudo -S`; if sudo fails (no sudo installed, wrong password, or the
  user simply has the needed rights like the `docker` group), SAT falls
  back to running the command plainly.
- **MOTD over SSH**: SFTP cannot sudo, so SAT writes a temp file in the
  user's home directory and `sudo cp`s it into place when the direct
  write is denied.
- **Locally**: SAT tries passwordless `sudo -n` first, then runs
  plainly; on Windows commands run directly.  Run SAT as a user with
  the needed rights or passwordless sudo.
- Servers with `Defaults requiretty` in sudoers cannot use the
  password-pipe approach; the fallback then applies.

## Security notes

- **Host keys**: SSH connections accept unknown host keys automatically
  (paramiko's `AutoAddPolicy`) for convenience.  For stricter security,
  change `SshRunner.connect()` to use `RejectPolicy` and populate
  `known_hosts`.
- **Passwords** are stored in plain text in the SAT config file
  (`~/.sat-data/hosts.json`, i.e. `C:\Users\<user>\.sat-data\hosts.json`
  on Windows).  Prefer SSH keys.
- **Permissions**: `systemctl` and `docker` need privileges on the
  server.  Connect as a user that can run them (for example, a sudo
  user, or a member of the `docker` group).
- **MOTD**: on Ubuntu/Debian, dynamic banners from `/etc/update-motd.d`
  can overwrite `/etc/motd`; editing the static file works best on
  servers without dynamic banners.
