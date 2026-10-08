"""The one function everything else calls: the command line, the MCP server, the HTTP server, and your own code.

    from whenfree import api
    result = api.find_free(api.Query(days="Thu 1 Oct, Fri 2 Oct", hours="10:00-16:00"))
    for day in result["days"]:
        print(day["label"], day["free"])

`find_free` returns plain data (dicts, lists, strings), so it can be turned into JSON as it is.
It raises `Problem` for anything the caller can fix: no calendar configured, a calendar that cannot be read,
dates that cannot be understood. It never returns slots when a calendar failed to load.

How it answers, step by step: resolve the settings (`_plan`), choose the days (one strategy per way of asking),
read the busy time from every calendar (`sources`), then work out each day (`slots`).
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from . import settings
from .calendars import sources
from .calendars.sources import NO_SLOTS, URL  # noqa: F401
from .core import ical, slots
from .core import status as standing
from .core.errors import Problem
from .core.render import label, lines  # noqa: F401  (kept here for existing callers)
from .messages import dates, extract

SETUP_HINT = """No calendar is configured.

  whenfree add           asks for your calendar's private iCal address, checks it and saves it
  whenfree init          only creates the settings file, for you to edit

Installed with uvx, or as a Claude Code plugin? Then it is: uvx when-free add

Or try it once without a settings file:

  whenfree --calendar ~/Downloads/calendar.ics"""


@dataclass
class Query:
    days: str | None = None             # "Thu 1 Oct, Fri 2 Oct", "2026-10-05, 2026-10-06" or "next week"
    start: str | None = None            # first day of a range, YYYY-MM-DD (default: today)
    end: str | None = None              # last day of a range, YYYY-MM-DD
    message: str | None = None          # text to read the proposed days and hours from
    hours: str | None = None            # "10:00-16:00" or "afternoon"
    min_minutes: int | None = None
    buffer_minutes: int | None = None
    timezone: str | None = None
    weekends: bool = False
    all_day_busy: bool = False
    calendars: list[str] | None = None  # addresses or paths, instead of the configured calendars
    config_path: str | None = None
    use_extract: bool = True            # run the [extract] command if one is configured


# ---------- settings ----------

def _settings(path: str | None) -> settings.Config:
    try:
        return settings.load(path)
    except settings.ConfigError as e:
        raise Problem(str(e)) from None


def _timezone(name: str | None, cfg: settings.Config) -> ZoneInfo:
    name = name or cfg.timezone or settings.system_timezone()
    try:
        return ZoneInfo(name)
    except Exception:
        raise Problem(f"unknown time zone {name!r}; use a name like Europe/London") from None


def _hours(value: str) -> tuple[dt.time, dt.time]:
    try:
        return dates.hours_from_string(value)
    except ValueError as e:
        raise Problem(str(e)) from None


def _calendars(given: list[str] | None, cfg: settings.Config) -> list[settings.Calendar]:
    if given:
        return [settings.Calendar(f"calendar {i}", s) for i, s in enumerate(given, 1)]
    if cfg.calendars:
        return cfg.calendars
    if cfg.path and cfg.path.exists():       # the usual case: the file is there and its url line is still empty
        raise Problem(SETUP_HINT.replace("No calendar is configured.",
                                         f"No calendar is configured: {cfg.path} has none with an address.", 1))
    raise Problem(SETUP_HINT)


# ---------- which days: one strategy per way of asking ----------

@dataclass
class _Chosen:
    days: list[dt.date]
    hours: tuple[dt.time, dt.time] | None = None    # read from the message, if it stated them
    minutes: int | None = None                      # the meeting length, if a model read one
    read_by: str | None = None                      # how a message was read


def _from_message(q: Query, cfg: settings.Config, today: dt.date) -> _Chosen:
    got = extract.run(cfg.extract_command, q.message, today) if (cfg.extract_command and q.use_extract) else None
    if got:
        try:
            hours = dates.hours_from_string(got["hours"]) if got["hours"] else None
        except ValueError:
            hours = None
        chosen = _Chosen(got["days"], hours, got["minutes"], "your model")
    else:
        chosen = _Chosen(dates.parse_days(q.message, today), dates.parse_hours(q.message), None, "pattern matching")
    if not chosen.days:
        raise Problem("found no dates in the message. Give them explicitly: days \"Thu 1 Oct, Fri 2 Oct\"")
    return chosen


def _listed(q: Query, cfg: settings.Config, today: dt.date) -> _Chosen:
    days = dates.parse_days(q.days, today)
    if not days:
        raise Problem(f"could not read any date from {q.days!r}. Examples: \"Thu 1 Oct, 5 Oct\", 2026-10-05, \"next week\"")
    return _Chosen(days)


def _in_range(q: Query, cfg: settings.Config, today: dt.date) -> _Chosen:
    try:
        first = dt.date.fromisoformat(q.start) if q.start else today
        last = dt.date.fromisoformat(q.end) if q.end else None
    except ValueError:
        raise Problem("the first and last day are dates like 2026-10-05") from None
    weekends = q.weekends or cfg.weekends
    if last is None:                                  # the next working days
        days, d = [], first
        while len(days) < cfg.days_ahead:
            if weekends or d.weekday() < 5:
                days.append(d)
            d += dt.timedelta(days=1)
        return _Chosen(days)
    if last < first:
        raise Problem("the last day is before the first day")
    every = (first + dt.timedelta(days=i) for i in range((last - first).days + 1))
    return _Chosen([d for d in every if weekends or d.weekday() < 5])


DayStrategy = Callable[[Query, settings.Config, dt.date], _Chosen]


def _strategy(q: Query) -> DayStrategy:
    if q.message:
        return _from_message
    if q.days:
        return _listed
    return _in_range


# ---------- the plan: every setting resolved, before any calendar is read ----------

@dataclass
class _Plan:
    tz: ZoneInfo
    now: dt.datetime
    days: list[dt.date]
    past: list[dt.date]
    opens: dt.time
    closes: dt.time
    min_minutes: int
    buffer_minutes: int
    all_day_busy: bool
    read_by: str | None
    calendars: list[settings.Calendar] = field(default_factory=list)


def _plan(q: Query, cfg: settings.Config) -> _Plan:
    tz = _timezone(q.timezone, cfg)
    now = settings.now(tz)
    min_minutes = q.min_minutes if q.min_minutes is not None else cfg.min_minutes
    buffer_minutes = q.buffer_minutes if q.buffer_minutes is not None else cfg.buffer_minutes
    if min_minutes < 1 or buffer_minutes < 0:
        raise Problem("min_minutes must be at least 1 and buffer_minutes cannot be negative")
    asked_hours = _hours(q.hours) if q.hours else None

    chosen = _strategy(q)(q, cfg, now.date())
    past = [d for d in chosen.days if d < now.date()]
    days = [d for d in chosen.days if d >= now.date()]
    if not days:
        raise Problem("every date asked for is already in the past")
    opens, closes = asked_hours or chosen.hours or _hours(cfg.hours)
    if q.min_minutes is None and chosen.minutes:
        min_minutes = chosen.minutes
    return _Plan(tz, now, days, past, opens, closes, min_minutes, buffer_minutes,
                 q.all_day_busy or cfg.all_day_busy, chosen.read_by, _calendars(q.calendars, cfg))


# ---------- the answer ----------

def _load_busy(calendars: list[settings.Calendar], tz, start: dt.date, end: dt.date, cfg: settings.Config,
               all_day_busy: bool, reader) -> tuple[list[slots.Busy], list[str], int]:
    """Busy blocks from every calendar between the start of `start` and the end of `end`."""
    window_start = dt.datetime.combine(start, dt.time.min, tz)
    window_end = dt.datetime.combine(end + dt.timedelta(days=1), dt.time.min, tz)
    busy: list[slots.Busy] = []
    notes: list[str] = []
    events_read = 0
    for name, events in sources.load(calendars, tz, reader=reader):
        events_read += len(events)
        busy += slots.busy_blocks(events, window_start, window_end, me=cfg.me, all_day_busy=all_day_busy,
                                  calendar=name, warnings=notes)
    busy.sort(key=lambda b: (b.start, b.end))
    return busy, notes, events_read


def _busy(plan: _Plan, cfg: settings.Config, reader) -> tuple[list[slots.Busy], list[str], int]:
    return _load_busy(plan.calendars, plan.tz, min(plan.days), max(plan.days), cfg, plan.all_day_busy, reader)


def _day(d: dt.date, plan: _Plan, busy: list[slots.Busy]) -> dict:
    clock = lambda t: t.astimezone(plan.tz).strftime("%H:%M")
    free = slots.free_slots(d, plan.opens, plan.closes, busy, plan.tz, buffer_minutes=plan.buffer_minutes,
                            min_minutes=plan.min_minutes, now=plan.now if d == plan.now.date() else None)
    day_start = dt.datetime.combine(d, dt.time.min, plan.tz)
    blocking = [b for b in busy if b.start < day_start + dt.timedelta(days=1) and b.end > day_start]
    return {
        "date": d.isoformat(), "label": label(d),
        "free": [[clock(a), clock(b)] for a, b in free],
        "busy": [{"start": clock(b.start), "end": clock(b.end), "title": b.title or "untitled", "calendar": b.calendar}
                 for b in blocking],
    }


def find_free(q: Query, *, reader: sources.Reader | None = None) -> dict:
    """Free slots for the days asked about. See the module docstring for the shape of the answer.

    `reader` turns a calendar's address or path into its text; by default it is fetched or read from disk.
    """
    cfg = _settings(q.config_path)
    plan = _plan(q, cfg)
    busy, notes, events_read = _busy(plan, cfg, reader)
    return {
        "timezone": plan.tz.key, "hours": [plan.opens.strftime("%H:%M"), plan.closes.strftime("%H:%M")],
        "min_minutes": plan.min_minutes, "buffer_minutes": plan.buffer_minutes,
        "days": [_day(d, plan, busy) for d in plan.days],
        "read_by": plan.read_by,                          # how the days were read from a message, or None
        "past": [d.isoformat() for d in plan.past],       # asked for, but already gone
        "notes": notes,
        "events_read": events_read, "calendars": len(plan.calendars), "blocking": len(busy),
    }


# ---------- right now ----------

def status(config_path: str | None = None, calendars: list[str] | None = None, timezone: str | None = None,
           *, min_minutes: int | None = None, reader: sources.Reader | None = None) -> dict:
    """Free or busy now, until when, and the next slot. For status bars, phones and smart homes. No titles."""
    cfg = _settings(config_path)
    tz = _timezone(timezone, cfg)
    now = settings.now(tz)
    opens, closes = _hours(cfg.hours)
    minutes = min_minutes if min_minutes is not None else cfg.min_minutes
    if minutes < 1:
        raise Problem("min_minutes must be at least 1")
    busy, notes, _ = _load_busy(_calendars(calendars, cfg), tz, now.date(), now.date() + dt.timedelta(days=14),
                                cfg, cfg.all_day_busy, reader)
    result = standing.status(busy, now, tz, opens, closes, buffer_minutes=cfg.buffer_minutes, min_minutes=minutes,
                             weekends=cfg.weekends)
    return {"timezone": tz.key, "min_minutes": minutes, **result, "notes": notes}


# ---------- checking and adding calendars ----------

def _found(name: str, events: list[ical.Event], cfg: settings.Config, now: dt.datetime) -> dict:
    blocks = slots.busy_blocks(events, now, now + dt.timedelta(days=14), me=cfg.me, all_day_busy=cfg.all_day_busy)
    return {"name": name, "events": len(events), "blocking_next_14_days": len(blocks)}


def check_calendars(config_path: str | None = None, calendars: list[str] | None = None,
                    timezone: str | None = None, *, reader: sources.Reader | None = None) -> dict:
    """Read every calendar and say what was found. Raises `Problem` if any cannot be read."""
    cfg = _settings(config_path)
    tz = _timezone(timezone, cfg)
    cals = _calendars(calendars, cfg)
    now = settings.now(tz)
    found = [_found(name, events, cfg, now) for name, events in sources.load(cals, tz, reader=reader)]
    return {"settings": str(cfg.path) if cfg.path and cfg.path.exists() else None, "timezone": tz.key, "calendars": found}


def add_calendar(source: str, name: str | None = None, config_path: str | None = None) -> dict:
    """Read a calendar and, only if it can be read, save it in the settings file. For `whenfree add`.

    It is not offered to agents as a tool: the address is a secret and should go from the person to the file.
    """
    cfg = _settings(config_path)
    tz = _timezone(None, cfg)
    (_, events), = sources.load([settings.Calendar(name or "new", source)], tz, consequence="Nothing was saved.")
    try:
        path, name = settings.add_calendar(source, name, cfg.path)
    except settings.ConfigError as e:
        raise Problem(str(e)) from None
    return {"settings": str(path), **_found(name, events, cfg, settings.now(tz))}
