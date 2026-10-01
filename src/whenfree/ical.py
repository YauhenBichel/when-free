"""Read iCalendar (RFC 5545) text into events and expand the recurring ones. Standard library only.

This is not a complete RFC 5545 implementation. It covers what calendar feeds from Google, Outlook and
iCloud actually contain for ordinary meetings: timed and all-day events, time zones by TZID, free/busy
transparency, cancelled events, attendee replies, EXDATE, per-instance overrides (RECURRENCE-ID) and the
common recurrence rules. A rule it cannot expand raises `Unsupported`, and the caller decides what to do.
"""
from __future__ import annotations

import calendar
import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Iterator
from zoneinfo import ZoneInfo

WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
UTC = dt.timezone.utc


class Unsupported(Exception):
    """A recurrence rule this module does not expand."""


@dataclass
class Event:
    start: dt.datetime
    end: dt.datetime
    summary: str = ""
    all_day: bool = False
    transparent: bool = False          # marked "Free" in the calendar
    cancelled: bool = False
    uid: str = ""
    rrule: dict[str, str] | None = None
    exdates: list[dt.datetime] = field(default_factory=list)
    recurrence_id: dt.datetime | None = None
    attendees: list[tuple[str, str]] = field(default_factory=list)   # (address in lower case, PARTSTAT)


# ---------- reading ----------

def _unfold(text: str) -> list[str]:
    return re.sub(r"\r?\n[ \t]", "", text).splitlines()


def _split_line(line: str) -> tuple[str, dict[str, str], str] | None:
    """NAME;PARAM=x;PARAM="a:b":value -> (NAME, params, value). Colons and semicolons inside quotes are data."""
    in_quotes, colon = False, -1
    for i, ch in enumerate(line):
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == ":" and not in_quotes:
            colon = i
            break
    if colon < 0:
        return None
    head, value = line[:colon], line[colon + 1:]
    parts = re.split(r';(?=(?:[^"]*"[^"]*")*[^"]*$)', head)
    params = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.upper()] = v.strip('"')
    return parts[0].upper(), params, value


def _parse_dt(value: str, params: dict[str, str], default_tz: dt.tzinfo) -> tuple[dt.datetime, bool]:
    """Return (aware datetime, is a whole-day value)."""
    value = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        return dt.datetime.strptime(value[:8], "%Y%m%d").replace(tzinfo=default_tz), True
    if value.endswith("Z"):
        return dt.datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC), False
    naive = dt.datetime.strptime(value, "%Y%m%dT%H%M%S")
    tz = default_tz
    if params.get("TZID"):
        try:
            tz = ZoneInfo(params["TZID"])
        except Exception:      # an Outlook-style zone name the tz database does not know: keep the default
            tz = default_tz
    return naive.replace(tzinfo=tz), False


_DURATION = re.compile(r"[+]?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


def _parse_duration(value: str) -> dt.timedelta | None:
    m = _DURATION.match(value.strip())
    if not m:
        return None
    w, d, h, mi, s = (int(x or 0) for x in m.groups())
    return dt.timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)


def parse(text: str, default_tz: dt.tzinfo) -> list[Event]:
    """All VEVENTs in a calendar. Times without a zone are read in `default_tz`."""
    events: list[Event] = []
    cur: dict | None = None
    nested = 0                      # VALARM and friends inside a VEVENT are skipped
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            cur, nested = {"exdates": [], "attendees": []}, 0
            continue
        if cur is None:
            continue
        if line.startswith("BEGIN:"):
            nested += 1
            continue
        if line.startswith("END:") and nested:
            nested -= 1
            continue
        if line == "END:VEVENT":
            if "start" in cur:
                start = cur["start"]
                if "end" in cur:
                    end = cur["end"]
                elif cur.get("duration") is not None:
                    end = start + cur["duration"]
                else:
                    end = start + dt.timedelta(days=1) if cur.get("all_day") else start
                events.append(Event(
                    start=start, end=end, summary=cur.get("summary", ""), all_day=cur.get("all_day", False),
                    transparent=cur.get("transp") == "TRANSPARENT", cancelled=cur.get("status") == "CANCELLED",
                    uid=cur.get("uid", ""), rrule=cur.get("rrule"), exdates=cur["exdates"],
                    recurrence_id=cur.get("recurrence_id"), attendees=cur["attendees"]))
            cur = None
            continue
        if nested:
            continue
        split = _split_line(line)
        if not split:
            continue
        name, params, value = split
        if name == "DTSTART":
            cur["start"], cur["all_day"] = _parse_dt(value, params, default_tz)
        elif name == "DTEND":
            cur["end"], _ = _parse_dt(value, params, default_tz)
        elif name == "DURATION":
            cur["duration"] = _parse_duration(value)
        elif name == "SUMMARY":
            cur["summary"] = value.replace("\\,", ",").replace("\\;", ";").replace("\\n", " ").replace("\\N", " ")
        elif name == "TRANSP":
            cur["transp"] = value.strip().upper()
        elif name == "STATUS":
            cur["status"] = value.strip().upper()
        elif name == "UID":
            cur["uid"] = value.strip()
        elif name == "RRULE":
            cur["rrule"] = {k.upper(): v for k, v in (kv.split("=", 1) for kv in value.split(";") if "=" in kv)}
        elif name == "EXDATE":
            for v in value.split(","):
                if v.strip():
                    cur["exdates"].append(_parse_dt(v, params, default_tz)[0])
        elif name == "RECURRENCE-ID":
            cur["recurrence_id"] = _parse_dt(value, params, default_tz)[0]
        elif name == "ATTENDEE":
            cur["attendees"].append((value.strip().lower(), params.get("PARTSTAT", "").upper()))
    return events


# ---------- recurrence ----------

_NOT_EXPANDED = ("BYSETPOS", "BYWEEKNO", "BYYEARDAY", "BYHOUR", "BYMINUTE", "BYSECOND")


def _month_days(year: int, month: int, tokens: list[str]) -> list[dt.date]:
    """BYDAY inside a month: '1MO' is the first Monday, '-1FR' the last Friday, 'WE' every Wednesday."""
    last = calendar.monthrange(year, month)[1]
    out: set[dt.date] = set()
    for tok in tokens:
        m = re.fullmatch(r"([+-]?\d+)?(MO|TU|WE|TH|FR|SA|SU)", tok.strip().upper())
        if not m:
            raise Unsupported(f"BYDAY={tok}")
        wd = WEEKDAYS.index(m.group(2))
        days = [dt.date(year, month, d) for d in range(1, last + 1) if dt.date(year, month, d).weekday() == wd]
        if m.group(1):
            n = int(m.group(1))
            idx = n - 1 if n > 0 else n
            if -len(days) <= idx < len(days):
                out.add(days[idx])
        else:
            out.update(days)
    return sorted(out)


def _starts(ev: Event, window_start: dt.datetime) -> Iterator[dt.datetime]:
    """Occurrence starts in ascending order, without COUNT, UNTIL or EXDATE applied. Never ends on its own.

    Wall-clock time is kept across daylight-saving changes: a 09:30 meeting stays at 09:30.
    """
    rule, start = ev.rrule or {}, ev.start
    tz, clock = start.tzinfo, start.time()
    freq = rule.get("FREQ", "").upper()
    interval = max(1, int(rule.get("INTERVAL", "1")))
    tokens = [t for t in rule.get("BYDAY", "").split(",") if t]
    if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY") or any(k in rule for k in _NOT_EXPANDED):
        raise Unsupported(";".join(f"{k}={v}" for k, v in rule.items()))
    at = lambda day: dt.datetime.combine(day, clock, tz)
    # Without COUNT the early occurrences do not matter, so jump close to the window instead of walking years.
    can_skip = "COUNT" not in rule
    first_day = start.date()
    near = window_start.astimezone(tz).date() if tz else window_start.date()

    if freq == "DAILY":
        wanted = {WEEKDAYS.index(t[-2:].upper()) for t in tokens} if tokens else None
        day = first_day
        if can_skip and near > day:
            day += dt.timedelta(days=max(0, (near - day).days // interval - 1) * interval)
        while True:
            if wanted is None or day.weekday() in wanted:
                yield at(day)
            day += dt.timedelta(days=interval)

    elif freq == "WEEKLY":
        days = sorted({WEEKDAYS.index(t[-2:].upper()) for t in tokens}) if tokens else [first_day.weekday()]
        week = first_day - dt.timedelta(days=first_day.weekday())
        if can_skip and near > week:
            week += dt.timedelta(weeks=max(0, (near - week).days // 7 // interval - 1) * interval)
        while True:
            for wd in days:
                c = at(week + dt.timedelta(days=wd))
                if c >= start:
                    yield c
            week += dt.timedelta(weeks=interval)

    elif freq == "MONTHLY":
        year, month = first_day.year, first_day.month
        while True:
            last = calendar.monthrange(year, month)[1]
            if tokens:
                dates = _month_days(year, month, tokens)
            elif "BYMONTHDAY" in rule:
                dates = []
                for x in rule["BYMONTHDAY"].split(","):
                    n = int(x)
                    day = n if n > 0 else last + n + 1
                    if 1 <= day <= last:
                        dates.append(dt.date(year, month, day))
                dates.sort()
            else:
                dates = [dt.date(year, month, first_day.day)] if first_day.day <= last else []
            for d in dates:
                c = at(d)
                if c >= start:
                    yield c
            month += interval
            year, month = year + (month - 1) // 12, (month - 1) % 12 + 1

    else:  # YEARLY, on the same month and day
        if tokens or "BYMONTH" in rule or "BYMONTHDAY" in rule:
            raise Unsupported(";".join(f"{k}={v}" for k, v in rule.items()))
        year = first_day.year
        while True:
            try:
                yield at(dt.date(year, first_day.month, first_day.day))
            except ValueError:      # 29 February in a year without one
                pass
            year += interval


def _minute(t: dt.datetime) -> dt.datetime:
    return t.astimezone(UTC).replace(second=0, microsecond=0)


def expand(ev: Event, window_start: dt.datetime, window_end: dt.datetime) -> Iterator[tuple[dt.datetime, dt.datetime]]:
    """(start, end) of every occurrence that overlaps the window. Raises `Unsupported` for rules not expanded."""
    duration = ev.end - ev.start
    if not ev.rrule:
        if ev.start < window_end and ev.end > window_start:
            yield ev.start, ev.end
        return
    rule = ev.rrule
    count = int(rule["COUNT"]) if "COUNT" in rule else None
    until = None
    if "UNTIL" in rule:
        until, whole_day = _parse_dt(rule["UNTIL"], {}, ev.start.tzinfo or UTC)
        if whole_day:
            until += dt.timedelta(days=1) - dt.timedelta(seconds=1)
    excluded = {_minute(x) for x in ev.exdates}
    produced = 0
    for i, start in enumerate(_starts(ev, window_start)):
        if i > 200_000:             # a guard, not a limit anyone should reach
            break
        if until is not None and start > until:
            break
        if count is not None and produced >= count:
            break
        produced += 1               # COUNT includes occurrences that EXDATE later removes
        if start >= window_end:
            break
        if start + duration > window_start and _minute(start) not in excluded:
            yield start, start + duration
