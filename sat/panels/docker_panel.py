"""Docker management: containers, images and volumes with start, stop,
restart, logs, inspect, pull, prune, container creation and more."""

import shlex

import wx

from sat.announce import announce
from sat.util import run_in_thread

MODES = ["Containers", "Images", "Volumes"]
CONTAINER_FILTERS = ["All", "Running", "Exited"]


class DockerCreateDialog(wx.Dialog):
    """Collect everything needed to run a new container and build the
    matching `docker run` command."""

    def __init__(self, parent):
        super().__init__(parent, title="Create container", size=(500, 440))
        grid = wx.GridBagSizer(8, 8)
        row = 0

        self.image_text = self._field(grid, row, "Image (required):", "")
        row += 1
        self.name_text = self._field(grid, row, "Container name:", "")
        row += 1
        self.ports_text = self._field(
            grid, row, "Ports (e.g. 8080:80):", "")
        row += 1
        self.volumes_text = self._field(
            grid, row, "Volumes (e.g. /data:/data):", "")
        row += 1
        self.env_text = self._field(
            grid, row, "Environment (e.g. FOO=bar):", "")
        row += 1
        grid.Add(wx.StaticText(self, label="Restart policy:"), (row, 0),
                 flag=wx.ALIGN_CENTER_VERTICAL)
        self.restart_choice = wx.Choice(self, choices=["no", "always",
                                                       "unless-stopped"])
        self.restart_choice.SetSelection(0)
        grid.Add(self.restart_choice, (row, 1), flag=wx.EXPAND)
        row += 1
        self.command_text = self._field(grid, row, "Command (optional):", "")
        grid.AddGrowableCol(1)

        btns = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(grid, 1, wx.EXPAND | wx.ALL, 12)
        sizer.Add(btns, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(sizer)
        self.image_text.SetFocus()

    def _field(self, grid, row, label, value):
        grid.Add(wx.StaticText(self, label=label), (row, 0),
                 flag=wx.ALIGN_CENTER_VERTICAL)
        ctrl = wx.TextCtrl(self, value=value)
        grid.Add(ctrl, (row, 1), flag=wx.EXPAND)
        return ctrl

    @staticmethod
    def _split(text):
        return [part for part in text.replace(",", " ").split() if part]

    def command(self):
        """Build the docker run command from the dialog fields."""
        parts = ["docker", "run", "-d"]
        name = self.name_text.GetValue().strip()
        if name:
            parts += ["--name", name]
        for p in self._split(self.ports_text.GetValue()):
            parts += ["-p", p]
        for v in self._split(self.volumes_text.GetValue()):
            parts += ["-v", v]
        for e in self._split(self.env_text.GetValue()):
            parts += ["-e", e]
        restart = self.restart_choice.GetStringSelection()
        if restart != "no":
            parts += ["--restart", restart]
        parts.append(self.image_text.GetValue().strip())
        cmd = self.command_text.GetValue().strip()
        if cmd:
            parts += shlex.split(cmd)
        return " ".join(shlex.quote(p) for p in parts)

    def _on_ok(self, event):
        if not self.image_text.GetValue().strip():
            wx.MessageBox("Please enter an image name, for example "
                          "nginx:latest.", "Missing image",
                          wx.OK | wx.ICON_INFORMATION)
            return
        self.EndModal(wx.ID_OK)

CONTAINER_FORMAT = 'docker ps -a --no-trunc --format "{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}"'
IMAGE_FORMAT = 'docker images --format "{{.Repository}}:{{.Tag}}|{{.ID}}|{{.Size}}"'
VOLUME_FORMAT = 'docker volume ls --format "{{.Name}}"'


class DockerPanel(wx.Panel):
    def __init__(self, parent, frame):
        super().__init__(parent)
        self.frame = frame
        self._items = []  # (id_or_name, label)
        self._build_ui()
        self._bind_events()
        self._update_buttons()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        outer = wx.BoxSizer(wx.VERTICAL)

        top = wx.BoxSizer(wx.HORIZONTAL)
        top.Add(wx.StaticText(self, label="Show:"), 0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.mode_choice = wx.Choice(self, choices=MODES)
        self.mode_choice.SetSelection(0)
        top.Add(self.mode_choice, 0, wx.RIGHT, 12)
        top.Add(wx.StaticText(self, label="Filter:"), 0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.filter_choice = wx.Choice(self, choices=CONTAINER_FILTERS)
        self.filter_choice.SetSelection(0)
        top.Add(self.filter_choice, 0, wx.RIGHT, 12)
        top.Add(wx.StaticText(self, label="Search:"), 0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.search_text = wx.TextCtrl(self)
        top.Add(self.search_text, 1, wx.EXPAND)
        self.refresh_btn = wx.Button(self, label="&Refresh")
        top.Add(self.refresh_btn, 0, wx.LEFT, 12)
        outer.Add(top, 0, wx.EXPAND | wx.ALL, 8)

        outer.Add(wx.StaticText(self, label="Items:"), 0,
                  wx.LEFT | wx.RIGHT, 8)
        self.items_list = wx.ListBox(self)
        outer.Add(self.items_list, 1, wx.EXPAND | wx.ALL, 8)

        actions = wx.WrapSizer(wx.HORIZONTAL)
        self.start_btn = wx.Button(self, label="&Start")
        self.stop_btn = wx.Button(self, label="S&top")
        self.restart_btn = wx.Button(self, label="&Restart")
        self.pause_btn = wx.Button(self, label="&Pause")
        self.unpause_btn = wx.Button(self, label="&Unpause")
        self.remove_btn = wx.Button(self, label="&Remove")
        self.logs_btn = wx.Button(self, label="&Logs")
        self.inspect_btn = wx.Button(self, label="&Inspect")
        self.pull_btn = wx.Button(self, label="&Pull image")
        self.create_container_btn = wx.Button(self, label="Create c&ontainer")
        self.create_btn = wx.Button(self, label="Create &volume")
        self.prune_btn = wx.Button(self, label="&Prune")
        for btn in (self.start_btn, self.stop_btn, self.restart_btn,
                    self.pause_btn, self.unpause_btn, self.remove_btn,
                    self.logs_btn, self.inspect_btn, self.pull_btn,
                    self.create_container_btn, self.create_btn, self.prune_btn):
            actions.Add(btn, 0, wx.RIGHT, 6)
        outer.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        outer.Add(wx.StaticText(self, label="Output:"), 0,
                  wx.LEFT | wx.RIGHT, 8)
        self.output = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY)
        outer.Add(self.output, 2, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(outer)

    def _bind_events(self):
        self.refresh_btn.Bind(wx.EVT_BUTTON, lambda e: self.refresh())
        self.mode_choice.Bind(wx.EVT_CHOICE, self._on_mode)
        self.filter_choice.Bind(wx.EVT_CHOICE, lambda e: self._apply_filters())
        self.search_text.Bind(wx.EVT_TEXT, lambda e: self._apply_filters())
        self.items_list.Bind(wx.EVT_LISTBOX, self._on_selected)

        self.start_btn.Bind(wx.EVT_BUTTON, lambda e: self._container_cmd("start"))
        self.stop_btn.Bind(wx.EVT_BUTTON, lambda e: self._container_cmd("stop"))
        self.restart_btn.Bind(wx.EVT_BUTTON, lambda e: self._container_cmd("restart"))
        self.pause_btn.Bind(wx.EVT_BUTTON, lambda e: self._container_cmd("pause"))
        self.unpause_btn.Bind(wx.EVT_BUTTON, lambda e: self._container_cmd("unpause"))
        self.remove_btn.Bind(wx.EVT_BUTTON, lambda e: self._remove_selected())
        self.logs_btn.Bind(wx.EVT_BUTTON, lambda e: self._logs_selected())
        self.inspect_btn.Bind(wx.EVT_BUTTON, lambda e: self._inspect_selected())
        self.pull_btn.Bind(wx.EVT_BUTTON, lambda e: self._pull_image())
        self.create_container_btn.Bind(wx.EVT_BUTTON,
                                       lambda e: self._create_container())
        self.create_btn.Bind(wx.EVT_BUTTON, lambda e: self._create_volume())
        self.prune_btn.Bind(wx.EVT_BUTTON, lambda e: self._prune())

    # ------------------------------------------------------------- helpers

    def _set_output(self, text):
        self.output.SetValue(text or "(no output)")

    def _selected_id(self):
        sel = self.items_list.GetSelection()
        if sel == wx.NOT_FOUND:
            announce(self, "Nothing selected. Use the arrow keys to choose an item.")
            return None
        return self._items[sel][0]

    def _mode(self):
        return self.mode_choice.GetStringSelection()

    # -------------------------------------------------------------- refresh

    def refresh(self):
        announce(self, f"Loading {self._mode().lower()}...")

        def work():
            command = {MODES[0]: CONTAINER_FORMAT,
                       MODES[1]: IMAGE_FORMAT,
                       MODES[2]: VOLUME_FORMAT}[self._mode()]
            return self.frame.runner.run_admin(command, timeout=60)

        run_in_thread(work, self._on_loaded)

    def _on_loaded(self, res):
        if not res.ok:
            self._items = []
            self.items_list.Clear()
            self._set_output(res.combined or res.error)
            announce(self, "Could not list Docker items. " +
                     (res.error or self._first_line(res.stderr)))
            return
        items = []
        for line in res.stdout.splitlines():
            parts = line.split("|")
            if self._mode() == MODES[0] and len(parts) >= 4:
                cid, names, image, status = parts[0], parts[1], parts[2], parts[3]
                items.append((cid, f"{names}, {status}, image {image}"))
            elif self._mode() == MODES[1] and len(parts) >= 3:
                repo, iid, size = parts[0], parts[1], parts[2]
                items.append((iid, f"{repo}, {size}"))
            elif self._mode() == MODES[2] and parts[0].strip():
                items.append((parts[0].strip(), parts[0].strip()))
        self._items = items
        self._apply_filters(focus_list=True)

    def _first_line(self, text):
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return lines[0] if lines else ""

    def _apply_filters(self, focus_list=False):
        needle = self.search_text.GetValue().strip().lower()
        shown = []
        for ident, label in self._items:
            if needle and needle not in ident.lower() and needle not in label.lower():
                continue
            if self._mode() == MODES[0]:
                state = self.filter_choice.GetStringSelection().lower()
                if state != "all":
                    if state == "running" and "up " not in label.lower():
                        continue
                    if state == "exited" and "exited" not in label.lower():
                        continue
            shown.append(label)
        self.items_list.Set(shown)
        if shown:
            self.items_list.SetSelection(0)
            announce(self, f"{len(shown)} items shown. " + shown[0])
        else:
            announce(self, "No items match.")
        if focus_list:
            self.items_list.SetFocus()

    def _on_selected(self, event):
        sel = event.GetSelection()
        if 0 <= sel < self.items_list.GetCount():
            announce(self, self.items_list.GetString(sel))

    def _on_mode(self, event):
        self._update_buttons()
        self.refresh()

    def _update_buttons(self):
        mode = self._mode()
        container = mode == MODES[0]
        image = mode == MODES[1]
        volume = mode == MODES[2]
        for btn in (self.start_btn, self.stop_btn, self.restart_btn,
                    self.pause_btn, self.unpause_btn, self.logs_btn):
            btn.Enable(container)
        self.remove_btn.Enable(container or image or volume)
        self.inspect_btn.Enable(container or image or volume)
        self.pull_btn.Enable(image)
        self.create_container_btn.Enable(container)
        self.create_btn.Enable(volume)
        self.prune_btn.Enable(container or image)
        self.filter_choice.Enable(container)

    # -------------------------------------------------------------- actions

    def _container_cmd(self, verb):
        ident = self._selected_id()
        if not ident:
            return
        command = f"docker {verb} {ident}"
        label = f"{verb} {ident}"
        self._run(command, label)

    def _remove_selected(self):
        ident = self._selected_id()
        if not ident:
            return
        if wx.MessageBox(f"Remove {self._mode().lower()} {ident}?",
                         "Confirm removal",
                         wx.YES_NO | wx.ICON_WARNING) != wx.YES:
            return
        if self._mode() == MODES[0]:
            command = f"docker rm -f {ident}"
        elif self._mode() == MODES[1]:
            command = f"docker rmi -f {ident}"
        else:
            command = f"docker volume rm {ident}"
        self._run(command, f"remove {ident}")

    def _logs_selected(self):
        ident = self._selected_id()
        if not ident:
            return
        self._run(f"docker logs --tail 100 {ident}", f"logs for {ident}")

    def _inspect_selected(self):
        ident = self._selected_id()
        if not ident:
            return
        if self._mode() == MODES[2]:
            command = f"docker volume inspect {ident}"
        else:
            command = f"docker inspect {ident}"
        self._run(command, f"inspect {ident}", refresh_after=False)

    def _pull_image(self):
        name = wx.GetTextFromUser(
            "Image name and tag to pull, for example nginx:latest",
            "Pull image", default_value="", parent=self)
        if not name.strip():
            return
        self._run(f"docker pull {name.strip()}", f"pull {name.strip()}",
                  refresh_after=False, timeout=600)

    def _create_container(self):
        dlg = DockerCreateDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            command = dlg.command()
            self._run(command, "create container", refresh_after=True,
                      timeout=600)
        dlg.Destroy()

    def _create_volume(self):
        name = wx.GetTextFromUser(
            "Name for the new volume", "Create volume",
            default_value="", parent=self)
        if not name.strip():
            return
        self._run(f"docker volume create {name.strip()}",
                  f"create volume {name.strip()}")

    def _prune(self):
        if wx.MessageBox(
                "Prune removes unused Docker data and cannot be undone. "
                "Continue?", "Confirm prune",
                wx.YES_NO | wx.ICON_WARNING) != wx.YES:
            return
        self._run("docker system prune -af", "prune unused Docker data",
                  timeout=600)

    def _run(self, command, label, refresh_after=True, timeout=90):
        self._set_output(f"Running: {command}\n")
        announce(self, f"Running {label}...")

        def work():
            return self.frame.runner.run_admin(command, timeout=timeout)

        def done(res):
            self._set_output(res.combined or res.error or "No output")
            announce(self, f"{label}: {res.summary()}")
            if refresh_after:
                self.refresh()

        run_in_thread(work, done)

    # ------------------------------------------------------------- external

    def focus_output(self):
        self.output.SetFocus()

    def describe_state(self):
        sel = self.items_list.GetSelection()
        if 0 <= sel < self.items_list.GetCount():
            return f"Docker {self._mode().lower()}, " \
                   f"{self.items_list.GetCount()} items, selected: " + \
                self.items_list.GetString(sel)
        return f"Docker {self._mode().lower()}, no items loaded"
