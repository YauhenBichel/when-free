"""Readers that remember a calendar for a few minutes, for front ends that ask often (status bars, phones, MQTT).

Both wrap another reader and are readers themselves, so the rest of the code does not know they are there.
The disk cache is for commands that start fresh every time (a status bar runs `whenfree now` each minute): files
are named by a hash of the address, never the address, and are readable only by you.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import threading
import time

from . import sources


class MemoryCache:
    """For a long-running process: `whenfree serve`, `whenfree mqtt`."""

    def __init__(self, seconds: float, reader: sources.Reader | None = None, clock=time.monotonic):
        self.seconds, self.reader, self.clock = seconds, reader or sources.read, clock
        self._kept: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def __call__(self, source: str) -> str:
        with self._lock:
            kept = self._kept.get(source)
            if kept and self.clock() - kept[0] < self.seconds:
                return kept[1]
        text = self.reader(source)                   # outside the lock: one slow feed does not hold up the others
        with self._lock:
            self._kept[source] = (self.clock(), text)
        return text


def cache_dir() -> pathlib.Path:
    base = os.environ.get("XDG_CACHE_HOME") or pathlib.Path.home() / ".cache"
    return pathlib.Path(base) / "when-free"


class DiskCache:
    """For a command that runs again and again."""

    def __init__(self, seconds: float, reader: sources.Reader | None = None, folder: pathlib.Path | None = None):
        self.seconds, self.reader = seconds, reader or sources.read
        self.folder = folder or cache_dir()

    def __call__(self, source: str) -> str:
        if not sources.is_address(source):
            return self.reader(source)               # a file on disk is already local
        path = self.folder / (hashlib.sha256(source.encode()).hexdigest()[:32] + ".ics")
        try:
            if time.time() - path.stat().st_mtime < self.seconds:
                return path.read_text(encoding="utf-8")
        except OSError:
            pass
        text = self.reader(source)
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            os.chmod(self.folder, 0o700)
            tmp = path.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, path)
        except OSError:
            pass                                     # a cache that cannot be written is only slower
        return text
