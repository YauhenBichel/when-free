"""Phones, tablets and other devices allowed to ask `whenfree serve`, each with its own token.

Only a hash of each token is kept, in `devices.json` next to the settings file, readable only by you. The token
itself is shown once, when the device is added, inside the address it opens. Remove a device and its token stops
working at once; the others are not affected.

A device sees what you could tell anyone: free time and whether you are free now. Never event titles.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import pathlib
import secrets
from dataclasses import asdict, dataclass

from .. import settings

# What a device token may do. The owner's token (whenfree serve's own) may do everything.
DEVICE_TOOLS = ("free_slots", "status")


@dataclass
class Device:
    name: str
    token_sha256: str
    added: str


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def store_path(config_path: str | None = None) -> pathlib.Path:
    base = pathlib.Path(config_path).expanduser() if config_path else settings.default_path()
    return base.parent / "devices.json"


class Devices:
    def __init__(self, path: pathlib.Path):
        self.path = path

    def all(self) -> list[Device]:
        try:
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as e:
            raise settings.ConfigError(f"{self.path}: {e}") from None
        return [Device(**d) for d in data.get("devices", [])]

    def _save(self, devices: list[Device]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"devices": [asdict(d) for d in devices]}, f, indent=2)
        os.replace(tmp, self.path)

    def add(self, name: str) -> tuple[Device, str]:
        """A new device and its token. The token is not kept: show it now or never."""
        name = " ".join(name.split())
        if not name:
            raise settings.ConfigError("give the device a name, like \"Alex's iPhone\"")
        devices = self.all()
        if any(d.name.lower() == name.lower() for d in devices):
            raise settings.ConfigError(f"there is already a device called {name!r}; remove it first or pick another name")
        token = secrets.token_urlsafe(32)
        device = Device(name, _hash(token), dt.datetime.now().astimezone().isoformat(timespec="minutes"))
        self._save(devices + [device])
        return device, token

    def remove(self, name: str) -> Device:
        devices = self.all()
        gone = [d for d in devices if d.name.lower() == name.strip().lower()]
        if not gone:
            raise settings.ConfigError(f"no device called {name!r}. See: whenfree devices list")
        self._save([d for d in devices if d not in gone])
        return gone[0]

    def find(self, token: str) -> Device | None:
        """The device this token belongs to. Every hash is compared, in constant time."""
        if not token:
            return None
        wanted, found = _hash(token).encode(), None
        for d in self.all():
            if hmac.compare_digest(d.token_sha256.encode(), wanted):
                found = d
        return found
