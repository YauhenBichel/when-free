"""Token files next to the settings file. Mode 600. The settings file itself is not read here."""
from __future__ import annotations

import json
import os
import pathlib

from .. import settings


def directory(config_path: str | None) -> pathlib.Path:
    base = pathlib.Path(config_path).expanduser() if config_path else settings.default_path()
    return base.parent


def path(name: str, config_path: str | None) -> pathlib.Path:
    return directory(config_path) / name


def read(name: str, config_path: str | None) -> dict | None:
    file = path(name, config_path)
    if not file.is_file():
        return None
    try:
        data = json.loads(file.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write(name: str, config_path: str | None, data: dict) -> pathlib.Path:
    file = path(name, config_path)
    file.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data).encode()
    fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, raw)
    finally:
        os.close(fd)
    os.chmod(file, 0o600)
    return file


def exists(name: str, config_path: str | None) -> bool:
    data = read(name, config_path)
    return bool(data and data.get("access_token"))
