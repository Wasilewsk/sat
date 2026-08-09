"""Command execution backends: a local subprocess and SSH via paramiko.

Every panel talks to a Runner, so the same actions work on the local
machine and on any connected server.

Privileged commands go through ``run_admin``: over SSH the saved
password is fed to ``sudo -S`` (falling back to a plain run if sudo
fails), locally a passwordless ``sudo -n`` is tried first.  File writes
that are blocked by permissions fall back to writing a temp file and
moving it into place with sudo.
"""

import os
import posixpath
import shlex
import shutil
import socket
import subprocess
import tempfile
import time

import paramiko


class CommandResult:
    """Outcome of a single command."""

    def __init__(self, ok=False, stdout="", stderr="", error="", duration=0.0):
        self.ok = ok
        self.stdout = stdout
        self.stderr = stderr
        self.error = error
        self.duration = duration

    @property
    def combined(self):
        """stdout and stderr joined, ready to show to the user."""
        out = self.stdout
        if self.stderr:
            out = (out + "\n" if out else "") + self.stderr
        return out.strip("\n")

    def summary(self):
        if not self.ok:
            return self.error or "command failed"
        lines = [ln for ln in self.combined.splitlines() if ln.strip()]
        return f"done in {self.duration:.1f} seconds, {len(lines)} lines of output"


class Runner:
    """Interface implemented by LocalRunner and SshRunner."""

    def describe(self):
        raise NotImplementedError

    def run(self, command, timeout=30):
        raise NotImplementedError

    def run_admin(self, command, timeout=30):
        """Run a command that may need root privileges."""
        raise NotImplementedError

    def read_file(self, path):
        raise NotImplementedError

    def write_file(self, path, content):
        raise NotImplementedError

    def restore_backup(self, path):
        raise NotImplementedError

    def close(self):
        pass


class LocalRunner(Runner):
    """Runs commands on the machine SAT is running on."""

    def describe(self):
        return "Local machine"

    def run(self, command, timeout=30):
        t0 = time.time()
        try:
            if os.name == "nt":
                proc = subprocess.run(
                    command, shell=True, capture_output=True, text=True,
                    timeout=timeout)
            else:
                proc = subprocess.run(
                    ["bash", "-c", command], capture_output=True, text=True,
                    timeout=timeout)
        except subprocess.TimeoutExpired:
            return CommandResult(False, "", "",
                                 f"Command timed out after {timeout} seconds",
                                 time.time() - t0)
        except OSError as exc:
            return CommandResult(False, "", "",
                                 f"Could not run the command: {exc}",
                                 time.time() - t0)
        return CommandResult(proc.returncode == 0, proc.stdout, proc.stderr,
                             "", time.time() - t0)

    def run_admin(self, command, timeout=30):
        """Locally, try passwordless sudo first, then run plainly (the
        user may have the needed rights, or be in the docker group)."""
        if os.name == "nt":
            return self.run(command, timeout)
        res = self.run("sudo -n " + command, timeout)
        if res.ok:
            return res
        return self.run(command, timeout)

    def read_file(self, path):
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()

    def write_file(self, path, content):
        self._backup(path)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
        except PermissionError:
            self._sudo_write(path, content)

    def restore_backup(self, path):
        if not os.path.exists(path + ".bak"):
            raise FileNotFoundError(f"No backup exists for {path}")
        content = open(path + ".bak", "r", encoding="utf-8",
                       errors="replace").read()
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
        except PermissionError:
            self._sudo_write(path, content)

    def _backup(self, path):
        if os.path.exists(path):
            shutil.copy2(path, path + ".bak")

    def _sudo_write(self, path, content):
        tmp = tempfile.mktemp(prefix="sat-write-")
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(content)
            quoted = " ".join(shlex.quote(p) for p in (tmp, path))
            res = self.run(f"sudo -n cp {quoted} && rm -f {shlex.quote(tmp)}")
            if not res.ok:
                raise PermissionError(
                    res.error or res.combined or f"cannot write {path}")
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


class SshRunner(Runner):
    """Runs commands on a remote server over SSH using paramiko."""

    def __init__(self, host):
        self.host = host
        self._client = None
        self._home = None

    def describe(self):
        who = self.host.username or "unknown user"
        return f"{who}@{self.host.hostname}:{self.host.port}"

    def connect(self):
        if (self._client is not None and self._client.get_transport()
                and self._client.get_transport().is_active()):
            return
        client = paramiko.SSHClient()
        # Accept unknown host keys automatically: convenient for a
        # personal admin tool, but see the README security notes.
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs = dict(
            hostname=self.host.hostname,
            port=self.host.port,
            username=self.host.username,
            timeout=10,
            banner_timeout=15,
            auth_timeout=15,
        )
        if self.host.keyfile:
            kwargs["key_filename"] = self.host.keyfile
        if self.host.password:
            kwargs["password"] = self.host.password
        client.connect(**kwargs)
        self._client = client

    def close(self):
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def run(self, command, timeout=30, stdin_data=None):
        t0 = time.time()
        try:
            self.connect()
        except Exception as exc:
            self.close()
            return CommandResult(False, "", "", f"SSH connection failed: {exc}",
                                 time.time() - t0)
        try:
            chan = self._client.get_transport().open_session()
            chan.settimeout(timeout)
            chan.exec_command(command)
            if stdin_data:
                chan.sendall(stdin_data)
                chan.shutdown_write()
            stdout, stderr = b"", b""
            deadline = time.time() + timeout
            while True:
                while chan.recv_ready():
                    stdout += chan.recv(65536)
                while chan.recv_stderr_ready():
                    stderr += chan.recv_stderr(65536)
                if chan.exit_status_ready():
                    break
                if time.time() > deadline:
                    chan.close()
                    return CommandResult(False, "", "",
                                         f"Command timed out after {timeout} seconds",
                                         time.time() - t0)
                time.sleep(0.05)
            while chan.recv_ready():
                stdout += chan.recv(65536)
            while chan.recv_stderr_ready():
                stderr += chan.recv_stderr(65536)
            code = chan.recv_exit_status()
            chan.close()
            return CommandResult(
                code == 0,
                stdout.decode("utf-8", "replace"),
                stderr.decode("utf-8", "replace"),
                "", time.time() - t0)
        except (paramiko.SSHException, socket.timeout, OSError, EOFError) as exc:
            self.close()
            return CommandResult(False, "", "", f"SSH error: {exc}",
                                 time.time() - t0)

    def run_admin(self, command, timeout=30):
        """Run a privileged command.  Chain of attempts: the saved
        password piped to ``sudo -S``, then passwordless ``sudo -n``,
        then a plain run (for users that already have the needed
        rights, like the docker group or root)."""
        if self.host.password:
            res = self.run(f"sudo -S -p '' {command}", timeout,
                           stdin_data=self.host.password + "\n")
            if res.ok:
                return res
        res = self.run("sudo -n " + command, timeout)
        if res.ok:
            return res
        res = self.run(command, timeout)
        if not res.ok and self._looks_like_sudo_issue(res.combined):
            hint = (" (SAT could not use the saved password for sudo: "
                    "check the host password, or configure passwordless "
                    "sudo on the server.)")
            res.error = (res.error + " " if res.error else "") + hint
        return res

    @staticmethod
    def _looks_like_sudo_issue(text):
        low = text.lower()
        return ("a terminal is required" in low
                or "a password is required" in low
                or "requiretty" in low)

    # ------------------------------------------------------------- files

    def _home_dir(self):
        if self._home is None:
            res = self.run("printf '%s' \"$HOME\"")
            self._home = res.stdout.strip() or "."
        return self._home

    def read_file(self, path):
        self.connect()
        sftp = self._client.open_sftp()
        try:
            with sftp.open(path, "r") as fh:
                return fh.read().decode("utf-8", "replace")
        finally:
            sftp.close()

    def write_file(self, path, content):
        self._backup(path)
        self._write(path, content)

    def restore_backup(self, path):
        self.connect()
        sftp = self._client.open_sftp()
        try:
            with sftp.open(path + ".bak", "r") as bak:
                content = bak.read()
        except IOError:
            raise FileNotFoundError(f"No backup exists for {path}")
        finally:
            sftp.close()
        self._write(path, content.decode("utf-8", "replace"))

    def _backup(self, path):
        self.connect()
        sftp = self._client.open_sftp()
        try:
            try:
                with sftp.open(path, "r") as old:
                    current = old.read()
                with sftp.open(path + ".bak", "w") as bak:
                    bak.write(current)
            except IOError:
                pass  # no existing file, nothing to back up
        finally:
            sftp.close()

    def _write(self, path, content):
        """Write *content* to *path*, falling back to sudo when the
        direct SFTP write is denied (SFTP itself cannot sudo, so we
        write a temp file in $HOME and sudo-move it into place)."""
        try:
            self.connect()
            sftp = self._client.open_sftp()
            try:
                with sftp.open(path, "w") as fh:
                    fh.write(content)
            finally:
                sftp.close()
        except IOError:
            self._sudo_write(path, content)

    def _sudo_write(self, path, content):
        home = self._home_dir()
        tmp = posixpath.join(home, ".sat-write.tmp")
        sftp = self._client.open_sftp()
        try:
            with sftp.open(tmp, "w") as fh:
                fh.write(content)
        finally:
            sftp.close()
        quoted = " ".join(shlex.quote(p) for p in (tmp, path))
        res = self.run_admin(
            f"cp -f {quoted} && rm -f {shlex.quote(tmp)}", timeout=30)
        if not res.ok:
            raise PermissionError(
                res.error or res.combined or f"cannot write {path}")
