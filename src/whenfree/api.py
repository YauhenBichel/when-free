"""The one function everything else calls: the command line, the MCP server, and your own code.

    from whenfree import api
    result = api.find_free(api.Query(days="Thu 1 Oct, Fri 2 Oct", hours="10:00-16:00"))
    for day in result["days"]:
        print(day["label"], day["free"])

`find_free` returns plain data (dicts, lists, strings), so it can be turned into JSON as it is.
It raises `Problem` for anything the caller can fix: no calendar configured, a calendar that cannot be read,
dates that cannot be understood. It never returns slots when a calendar failed to load.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import urllib.error
import urllib.request
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from . import __version__, config as settings, dates, extract, ical, slots

DAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

SETUP_HINT = """No calendar is configured.

  whenfree add           asks for your calendar's private iCal address, checks it and saves it
  whenfree init          only creates the settings file, for you to edit

Or try it once without a settings file:

  whenfree --calendar ~/Downloads/calendar.ics"""

URL = ("http://", "https://", "webcal://")
NO_SLOTS = "No slots were printed, because without it busy time would look free."


class Problem(Exception):
    """Something the caller can fix. Its text is safe to show: it never contains a calendar address."""


@dataclass
class Query:
    days: str | None = None             # "Thu 1 Oct, Fri 2 Oct" or "2026-10-05, 2026-10-06"
    start: str | None = None            # first day of a range, YYYY-MM-DD (default: today)
    end: str | None = None              # last day of a range, YYYY-MM-DD
    message: str | None = None          # text to read the proposed days and hours from
    hours: str | None = None            # "10:00-16:00"
    min_minutes: int | None = None
    buffer_minutes: int | None = None
    timezone: str | None = None
    weekends: bool = False
    all_day_busy: bool = False
    calendars: list[str] | None = None  # addresses or paths, instead of the configured calendars
    config_path: str | None = None
    use_extract: bool = True            # run the [extract] command if one is configured


def _read(source: str) -> str:
    if source.startswith(URL):
        url = "https://" + source[len("webcal://"):] if source.startswith("webcal://") else source
        req = urllib.request.Request(url, headers={"User-Agent": f"when-free/{__version__}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    return pathlib.Path(source).expanduser().read_text(encoding="utf-8", errors="replace")


def _calendars(given: list[str] | None, cfg: settings.Config) -> list[settings.Calendar]:
    if given:
        return [settings.Calendar(f"calendar {i}", s) for i, s in enumerate(given, 1)]
    return cfg.calendars


def _hint(source: str, error: Exception) -> str:
    """What to try when an address is refused. It is built from the shape of the address and never quotes it."""
    if not source.startswith(URL) or not isinstance(error, urllib.error.HTTPError) or not 400 <= error.code < 500:
        return ""
    if "calendar.google.com" in source and "/public/" in source:
        return (" This is the calendar's public address, which works only for a calendar made public."
                " Copy \"Secret address in iCal format\" instead.")
    return " Copy the address again from the calendar's settings: part of it may be missing."


def _load(calendars: list[settings.Calendar], tz, consequence: str = NO_SLOTS) -> list[tuple[str, list[ical.Event]]]:
    """Every calendar or none: a calendar that silently fails to load would make busy time look free."""
    out = []
    for cal in calendars:
        try:
            text = _read(cal.source)
        except (OSError, urllib.error.URLError, ValueError) as e:
            # The address is a secret; name the calendar, never print where it lives.
            reason = getattr(e, "reason", None) or getattr(e, "strerror", None) or e.__class__.__name__
            raise Problem(f"could not read the calendar '{cal.name}' ({reason}). {consequence}"
                          f"{_hint(cal.source, e)}") from None
        if "BEGIN:VCALENDAR" not in text:
            if text.lstrip()[:200].lower().startswith(("<!doctype html", "<html")):
                raise Problem(f"the calendar '{cal.name}' returned a web page, not a calendar; "
                              "use the address that ends in .ics")
            raise Problem(f"the calendar '{cal.name}' did not return iCalendar data; check its address")
        out.append((cal.name, ical.parse(text, tz)))
    return out


def _timezone(name: str | None, cfg: settings.Config):
    name = name or cfg.timezone or settings.system_timezone()
    try:
        return ZoneInfo(name)
    except Exception:
        raise Problem(f"unknown time zone {name!r}; use a name like Europe/London") from None


def _working_days(start: dt.date, count: int, weekends: bool) -> list[dt.date]:
    days, d = [], start
    while len(days) < count:
        if weekends or d.weekday() < 5:
            days.append(d)
        d += dt.timedelta(days=1)
    return days


def label(d: dt.date) -> str:
    return f"{DAY[d.weekday()]} {d.day} {d.strftime('%b')}"


def find_free(q: Query) -> dict:
    """Free slots for the days asked about. See the module docstring for the shape of the answer."""
    try:
        cfg = settings.load(q.config_path)
    except settings.ConfigError as e:
        raise Problem(str(e)) from None
    tz = _timezone(q.timezone, cfg)
    now = settings.now(tz)
    today = now.date()
    min_minutes = q.min_minutes if q.min_minutes is not None else cfg.min_minutes
    buffer_minutes = q.buffer_minutes if q.buffer_minutes is not None else cfg.buffer_minutes
    if min_minutes < 1 or buffer_minutes < 0:
        raise Problem("min_minutes must be at least 1 and buffer_minutes cannot be negative")
    weekends = q.weekends or cfg.weekends
    try:
        hours = dates.hours_from_string(q.hours) if q.hours else None
    except ValueError as e:
        raise Problem(str(e)) from None
    read_by = None

    if q.message:
        got = extract.run(cfg.extract_command, q.message, today) if (cfg.extract_command and q.use_extract) else None
        if got:
            days, read_by = got["days"], "your model"
            if hours is None and got["hours"]:
                try:
                    hours = dates.hours_from_string(got["hours"])
                except ValueError:
                    pass
            if q.min_minutes is None and got["minutes"]:
                min_minutes = got["minutes"]
        else:
            days, read_by = dates.parse_days(q.message, today), "pattern matching"
            if hours is None:
                hours = dates.parse_hours(q.message)
        if not days:
            raise Problem("found no dates in the message. Give them explicitly: days \"Thu 1 Oct, Fri 2 Oct\"")
    elif q.days:
        days = dates.parse_days(q.days, today)
        if not days:
            raise Problem(f"could not read any date from {q.days!r}. Examples: \"Thu 1 Oct, 5 Oct\" or 2026-10-05")
    else:
        try:
            first = dt.date.fromisoformat(q.start) if q.start else today
            last = dt.date.fromisoformat(q.end) if q.end else None
        except ValueError:
            raise Problem("the first and last day are dates like 2026-10-05") from None
        if last is None:
            days = _working_days(first, cfg.days_ahead, weekends)
        else:
            if last < first:
                raise Problem("the last day is before the first day")
            days = [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]
            days = [d for d in days if weekends or d.weekday() < 5]

    past = [d for d in days if d < today]
    days = [d for d in days if d >= today]
    if not days:
        raise Problem("every date asked for is already in the past")
    opens, closes = hours or dates.hours_from_string(cfg.hours)

    calendars = _calendars(q.calendars, cfg)
    if not calendars:
        raise _no_calendar(cfg)
    window_start = dt.datetime.combine(min(days), dt.time.min, tz)
    window_end = dt.datetime.combine(max(days) + dt.timedelta(days=1), dt.time.min, tz)
    notes: list[str] = []
    busy: list[slots.Busy] = []
    events_read = 0
    for name, events in _load(calendars, tz):
        events_read += len(events)
        busy += slots.busy_blocks(events, window_start, window_end, me=cfg.me,
                                  all_day_busy=q.all_day_busy or cfg.all_day_busy, calendar=name, warnings=notes)
    busy.sort(key=lambda b: (b.start, b.end))

    clock = lambda t: t.astimezone(tz).strftime("%H:%M")
    out_days = []
    for d in days:
        free = slots.free_slots(d, opens, closes, busy, tz, buffer_minutes=buffer_minutes,
                                min_minutes=min_minutes, now=now if d == today else None)
        day_start = dt.datetime.combine(d, dt.time.min, tz)
        blocking = [b for b in busy if b.start < day_start + dt.timedelta(days=1) and b.end > day_start]
        out_days.append({
            "date": d.isoformat(), "label": label(d),
            "free": [[clock(a), clock(b)] for a, b in free],
            "busy": [{"start": clock(b.start), "end": clock(b.end), "title": b.title or "untitled", "calendar": b.calendar}
                     for b in blocking],
        })
    return {
        "timezone": tz.key, "hours": [opens.strftime("%H:%M"), closes.strftime("%H:%M")],
        "min_minutes": min_minutes, "buffer_minutes": buffer_minutes,
        "days": out_days,
        "read_by": read_by,                               # how the days were read from a message, or None
        "past": [d.isoformat() for d in past],            # asked for, but already gone
        "notes": notes,
        "events_read": events_read, "calendars": len(calendars), "blocking": len(busy),
    }


def lines(result: dict, busy: bool = False) -> list[str]:
    """The answer as text, one line per day, ready to paste into a reply."""
    out = []
    for day in result["days"]:
        free = ", ".join(f"{a}–{b}" for a, b in day["free"]) or "no free slot"
        out.append(f"- {day['label']}: {free}")
        if busy:
            for b in day["busy"]:
                where = f"  [{b['calendar']}]" if result["calendars"] > 1 else ""
                out.append(f"      busy {b['start']}–{b['end']}  {b['title']}{where}")
    return out


def _no_calendar(cfg: settings.Config) -> Problem:
    if cfg.path and cfg.path.exists():       # the usual case: the file is there and its url line is still empty
        return Problem(SETUP_HINT.replace("No calendar is configured.",
                                          f"No calendar is configured: {cfg.path} has none with an address.", 1))
    return Problem(SETUP_HINT)


def _found(name: str, events: list[ical.Event], cfg: settings.Config, now: dt.datetime) -> dict:
    blocks = slots.busy_blocks(events, now, now + dt.timedelta(days=14), me=cfg.me, all_day_busy=cfg.all_day_busy)
    return {"name": name, "events": len(events), "blocking_next_14_days": len(blocks)}


def check_calendars(config_path: str | None = None, calendars: list[str] | None = None,
                    timezone: str | None = None) -> dict:
    """Read every calendar and say what was found. Raises `Problem` if any cannot be read."""
    try:
        cfg = settings.load(config_path)
    except settings.ConfigError as e:
        raise Problem(str(e)) from None
    tz = _timezone(timezone, cfg)
    cals = _calendars(calendars, cfg)
    if not cals:
        raise _no_calendar(cfg)
    now = settings.now(tz)
    found = [_found(name, events, cfg, now) for name, events in _load(cals, tz)]
    return {"settings": str(cfg.path) if cfg.path and cfg.path.exists() else None, "timezone": tz.key, "calendars": found}


def add_calendar(source: str, name: str | None = None, config_path: str | None = None) -> dict:
    """Read a calendar and, only if it can be read, save it in the settings file. For `whenfree add`.

    It is not offered to agents as a tool: the address is a secret and should go from the person to the file.
    """
    try:
        cfg = settings.load(config_path)
    except settings.ConfigError as e:
        raise Problem(str(e)) from None
    tz = _timezone(None, cfg)
    (_, events), = _load([settings.Calendar(name or "new", source)], tz, consequence="Nothing was saved.")
    try:
        path, name = settings.add_calendar(source, name, cfg.path)
    except settings.ConfigError as e:
        raise Problem(str(e)) from None
    return {"settings": str(path), **_found(name, events, cfg, settings.now(tz))}
