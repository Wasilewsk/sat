"""Saved server definitions, persisted as JSON in the user's config dir."""

import json
import os


def config_dir():
    r"""Return the per-user data directory: ~/.sat-data, which is
    C:\Users\<user>\.sat-data on Windows."""
    return os.path.join(os.path.expanduser("~"), ".sat-data")


class Host:
    """One server definition.  ``local`` hosts are the machine SAT runs on."""

    def __init__(self, name="", hostname="", port=22, username="",
                 password="", keyfile="", local=False):
        self.name = name
        self.hostname = hostname
        self.port = port
        self.username = username
        self.password = password
        self.keyfile = keyfile
        self.local = local

    @classmethod
    def local_host(cls):
        return cls(name="Local machine", local=True)

    def to_dict(self):
        return {
            "name": self.name,
            "hostname": self.hostname,
            "port": self.port,
            "username": self.username,
            "password": self.password,
            "keyfile": self.keyfile,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            name=data.get("name", ""),
            hostname=data.get("hostname", ""),
            port=int(data.get("port") or 22),
            username=data.get("username", ""),
            password=data.get("password", ""),
            keyfile=data.get("keyfile", ""),
        )

    def describe(self):
        if self.local:
            return "Local machine"
        who = self.username or "unknown user"
        return f"{self.name} ({who}@{self.hostname}:{self.port})"


class HostStore:
    """Loads and saves the list of saved hosts."""

    def __init__(self, path=None):
        self.path = path or os.path.join(config_dir(), "hosts.json")
        self.hosts = []
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.hosts = [Host.from_dict(d) for d in data]
        except (OSError, ValueError):
            self.hosts = []

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump([h.to_dict() for h in self.hosts], fh, indent=2)
