"""Settings: a TOML file, then environment variables, then command-line flags. Nothing is required but a calendar."""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import tomllib
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo


class ConfigError(Exception):
    pass


@dataclass
class Calendar:
    name: str
    source: str          # an https:// address or a path to an .ics file


@dataclass
class Config:
    timezone: str | None = None            # None: the system's zone
    hours: str = "09:00-18:00"
    min_minutes: int = 60
    buffer_minutes: int = 15
    weekends: bool = False
    all_day_busy: bool = False
    days_ahead: int = 7
    me: list[str] = field(default_factory=list)
    calendars: list[Calendar] = field(default_factory=list)
    extract_command: list[str] | None = None
    path: pathlib.Path | None = None       # where it was read from, for messages


TEMPLATE = '''# when-free settings. Every line is optional except one calendar.
# This file holds private calendar addresses: keep it out of git and readable only by you.

# timezone = "Europe/London"     # default: your system's time zone
hours = "09:00-18:00"            # the part of the day you offer
min_minutes = 60                 # shortest slot worth offering
buffer_minutes = 15              # kept free before and after every event
weekends = false
all_day_busy = false             # true: whole-day events block the day (holidays), unless marked Free
days_ahead = 7                   # working days shown when you give no dates

# Your addresses. An invitation you declined does not block your time.
me = []                          # e.g. ["you@example.com"]

# One block per calendar. Use the private iCal address of the calendar, or a path to an .ics file.
#   Google Calendar: Settings -> your calendar -> Integrate calendar -> "Secret address in iCal format"
#   Outlook:         Settings -> Calendar -> Shared calendars -> Publish a calendar -> ICS link
#   iCloud:          Calendar -> share icon -> Public Calendar (replace webcal:// with https://)
[[calendar]]
name = "personal"
url = ""

# [[calendar]]
# name = "work"
# path = "~/calendars/work.ics"

# Optional. A command that reads the days and hours out of a pasted message with a model you run.
# The prompt replaces {prompt}; without {prompt} it is sent on standard input. It must print JSON.
# Without this, dates are read by pattern matching, which needs no model at all.
# [extract]
# command = ["ollama", "run", "llama3.2"]
'''


def default_path() -> pathlib.Path:
    if os.environ.get("WHENFREE_CONFIG"):
        return pathlib.Path(os.environ["WHENFREE_CONFIG"]).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or pathlib.Path.home() / ".config"
    return pathlib.Path(base) / "when-free" / "config.toml"


def system_timezone() -> str:
    if os.environ.get("TZ"):
        try:
            ZoneInfo(os.environ["TZ"])
            return os.environ["TZ"]
        except Exception:
            pass
    try:
        real = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in real:
            name = real.split("zoneinfo/", 1)[1]
            ZoneInfo(name)
            return name
    except Exception:
        pass
    return "UTC"


def load(path: pathlib.Path | str | None = None) -> Config:
    path = pathlib.Path(path).expanduser() if path else default_path()
    cfg = Config(path=path)
    if path.exists():
        try:
            data = tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{path}: {e}") from None
        for key, kind in (("timezone", str), ("hours", str), ("min_minutes", int), ("buffer_minutes", int),
                          ("weekends", bool), ("all_day_busy", bool), ("days_ahead", int)):
            if key in data:
                if not isinstance(data[key], kind) or (kind is int and isinstance(data[key], bool)):
                    raise ConfigError(f"{path}: {key} should be {kind.__name__}")
                setattr(cfg, key, data[key])
        me = data.get("me", [])
        cfg.me = [me] if isinstance(me, str) else [str(x) for x in me]
        for i, cal in enumerate(data.get("calendar", []), 1):
            source = cal.get("url") or cal.get("path")
            if source:
                cfg.calendars.append(Calendar(str(cal.get("name") or f"calendar {i}"), str(source)))
        cmd = (data.get("extract") or {}).get("command")
        if cmd:
            if not isinstance(cmd, list) or not all(isinstance(x, str) for x in cmd):
                raise ConfigError(f"{path}: [extract] command should be a list of strings")
            cfg.extract_command = cmd
    if os.environ.get("WHENFREE_CALENDARS"):        # comma-separated addresses or paths; replaces the file's list
        cfg.calendars = [Calendar(f"calendar {i}", s.strip())
                         for i, s in enumerate(os.environ["WHENFREE_CALENDARS"].split(","), 1) if s.strip()]
    if os.environ.get("WHENFREE_TZ"):
        cfg.timezone = os.environ["WHENFREE_TZ"]
    if cfg.timezone:
        try:
            ZoneInfo(cfg.timezone)
        except Exception:
            raise ConfigError(f"unknown time zone {cfg.timezone!r}; use a name like Europe/London") from None
    if cfg.min_minutes < 1 or cfg.buffer_minutes < 0 or cfg.days_ahead < 1:
        raise ConfigError("min_minutes and days_ahead must be at least 1, and buffer_minutes cannot be negative")
    return cfg


def write_template(path: pathlib.Path | None = None) -> pathlib.Path:
    """Create the settings file, readable only by its owner. Never overwrites one that exists."""
    path = path or default_path()
    if path.exists():
        raise ConfigError(f"{path} already exists; edit it, or delete it first")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(TEMPLATE)
    return path


def now(tz: dt.tzinfo) -> dt.datetime:
    """The current time, or WHENFREE_NOW (an ISO date-time) so that a run can be reproduced."""
    fixed = os.environ.get("WHENFREE_NOW")
    if fixed:
        t = dt.datetime.fromisoformat(fixed)
        return t if t.tzinfo else t.replace(tzinfo=tz)
    return dt.datetime.now(tz)
