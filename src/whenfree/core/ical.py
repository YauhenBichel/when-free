"""Read iCalendar (RFC 5545) text into events and expand the recurring ones. Standard library only.

This is not a complete RFC 5545 implementation. It covers what calendar feeds from Google, Outlook and
iCloud actually contain for ordinary meetings: timed and all-day events, time zones by TZID, free/busy
transparency, cancelled events, attendee replies, EXDATE, per-instance overrides (RECURRENCE-ID) and the
common recurrence rules. A rule it cannot expand raises `Unsupported`, and the caller decides what to do.

A feed is other people's data: anyone can send an invitation. So one event that cannot be read never stops
the rest from being read (`parse` leaves it out and says so), and every recurrence loop ends by itself.
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


_DATE_TIME = re.compile(r"(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})?(?:[.,]\d+)?(Z)?)?")


def _parse_dt(value: str, params: dict[str, str], default_tz: dt.tzinfo) -> tuple[dt.datetime, bool]:
    """Return (aware datetime, is a whole-day value). Raises ValueError for anything that is not a date or time.

    Two harmless departures from the standard are read: a lower-case "z" and fractions of a second (dropped).
    """
    m = _DATE_TIME.fullmatch(value.strip().upper())
    if not m:
        raise ValueError("not a date or a date and time")
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if m.group(4) is None or params.get("VALUE", "").upper() == "DATE":
        return dt.datetime(year, month, day, tzinfo=default_tz), True
    naive = dt.datetime(year, month, day, int(m.group(4)), int(m.group(5)), int(m.group(6) or 0))
    if m.group(7):
        return naive.replace(tzinfo=UTC), False
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


_NEEDED = ("DTSTART", "DTEND", "DURATION", "RECURRENCE-ID")      # without these the time it takes is unknown


def _title(cur: dict) -> str:
    title = cur.get("summary", "").strip() or "untitled"
    return f"'{title[:60]}{'…' if len(title) > 60 else ''}'"


def _finish(cur: dict, problems: list[str]) -> Event | None:
    """The event collected between BEGIN:VEVENT and END:VEVENT, or None with the reason added to `problems`."""
    unread = [name for name in cur["unread"] if name in _NEEDED]
    if unread and (cur.get("status") == "CANCELLED" or cur.get("transp") == "TRANSPARENT"):
        return None                                    # it would not have blocked time anyway
    if unread:
        problems.append(f"{_title(cur)} was left out: its {' and '.join(dict.fromkeys(unread))} could not be read. "
                        "Its time is not blocked, so check that event yourself")
        return None
    if "start" not in cur:
        return None
    start = cur["start"]
    try:
        if "end" in cur:
            end = cur["end"]
        elif cur.get("duration") is not None:
            end = start + cur["duration"]
        else:
            end = start + dt.timedelta(days=1) if cur.get("all_day") else start
        if end.astimezone(UTC) < start.astimezone(UTC):
            problems.append(f"{_title(cur)} was left out: it ends before it starts. "
                            "Its time is not blocked, so check that event yourself")
            return None
    except OverflowError:
        problems.append(f"{_title(cur)} was left out: its dates are out of range")
        return None
    if "EXDATE" in cur["unread"]:
        problems.append(f"{_title(cur)} has an excluded date that could not be read; that date is still counted as busy")
    return Event(
        start=start, end=end, summary=cur.get("summary", ""), all_day=cur.get("all_day", False),
        transparent=cur.get("transp") == "TRANSPARENT", cancelled=cur.get("status") == "CANCELLED",
        uid=cur.get("uid", ""), rrule=cur.get("rrule"), exdates=cur["exdates"],
        recurrence_id=cur.get("recurrence_id"), attendees=cur["attendees"])


def _read_property(cur: dict, name: str, params: dict[str, str], value: str, default_tz: dt.tzinfo) -> None:
    if name == "DTSTART":
        cur["start"], cur["all_day"] = _parse_dt(value, params, default_tz)
    elif name == "DTEND":
        cur["end"], _ = _parse_dt(value, params, default_tz)
    elif name == "DURATION":
        cur["duration"] = _parse_duration(value)
        if cur["duration"] is None:
            raise ValueError("not a duration")
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


def parse(text: str, default_tz: dt.tzinfo, problems: list[str] | None = None) -> list[Event]:
    """All VEVENTs in a calendar. Times without a zone are read in `default_tz`.

    An event whose times cannot be read is left out, and a line saying which one is added to `problems`:
    one bad event must not hide every other event, and must not pass for free time without a word.
    """
    problems = problems if problems is not None else []
    events: list[Event] = []
    cur: dict | None = None
    nested = 0                      # VALARM and friends inside a VEVENT are skipped
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            cur, nested = {"exdates": [], "attendees": [], "unread": []}, 0
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
            event = _finish(cur, problems)
            if event is not None:
                events.append(event)
            cur = None
            continue
        if nested:
            continue
        split = _split_line(line)
        if not split:
            continue
        name, params, value = split
        try:
            _read_property(cur, name, params, value, default_tz)
        except (ValueError, OverflowError):
            cur["unread"].append(name)
    return events


# ---------- recurrence ----------

_NOT_EXPANDED = ("BYSETPOS", "BYWEEKNO", "BYYEARDAY", "BYHOUR", "BYMINUTE", "BYSECOND")
_BYDAY = re.compile(r"([+-]?\d{1,2})?(MO|TU|WE|TH|FR|SA|SU)")
MAX_INTERVAL = 1000                 # every 1000 years is as good as never; larger numbers are not a calendar's
MAX_STEPS = 200_000                 # periods walked for one event: daily for five centuries


def _rule_text(rule: dict[str, str]) -> str:
    text = ";".join(f"{k}={v}" for k, v in rule.items())
    return text if len(text) <= 80 else text[:80] + "…"


def _number(rule: dict[str, str], key: str, default: int | None, lowest: int, highest: int | None = None) -> int | None:
    if key not in rule:
        return default
    try:
        n = int(rule[key].strip())
    except ValueError:
        raise Unsupported(_rule_text(rule)) from None
    if n < lowest or (highest is not None and n > highest):
        raise Unsupported(_rule_text(rule))
    return n


@dataclass
class _Rule:
    """A rule with every value checked, so that the loops below only ever see numbers they can count with."""
    freq: str
    interval: int
    count: int | None
    until: dt.datetime | None
    weekdays: list[tuple[int, int]]     # BYDAY as (ordinal or 0, weekday)
    month_days: list[int]               # BYMONTHDAY: 1..31, or -1..-31 counted from the end


def _checked(ev: Event) -> _Rule:
    """Raises `Unsupported` for a rule this module does not expand, and for one whose values make no sense."""
    rule = ev.rrule or {}
    freq = rule.get("FREQ", "").strip().upper()
    if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY") or any(k in rule for k in _NOT_EXPANDED):
        raise Unsupported(_rule_text(rule))
    weekdays = []
    for tok in (t.strip().upper() for t in rule.get("BYDAY", "").split(",")):
        if not tok:
            continue
        m = _BYDAY.fullmatch(tok)
        ordinal = int(m.group(1)) if m and m.group(1) else 0
        if not m or (m.group(1) and not 1 <= abs(ordinal) <= 5):
            raise Unsupported(_rule_text(rule))
        weekdays.append((ordinal, WEEKDAYS.index(m.group(2))))
    month_days = []
    if freq == "MONTHLY" and "BYMONTHDAY" in rule:
        for x in rule["BYMONTHDAY"].split(","):
            try:
                n = int(x.strip())
            except ValueError:
                raise Unsupported(_rule_text(rule)) from None
            if not 1 <= abs(n) <= 31:
                raise Unsupported(_rule_text(rule))
            month_days.append(n)
    if freq == "YEARLY" and (weekdays or "BYMONTH" in rule or "BYMONTHDAY" in rule):
        raise Unsupported(_rule_text(rule))
    until = None
    if "UNTIL" in rule:
        try:
            until, whole_day = _parse_dt(rule["UNTIL"], {}, ev.start.tzinfo or UTC)
            if whole_day:
                until += dt.timedelta(days=1) - dt.timedelta(seconds=1)
        except (ValueError, OverflowError):
            raise Unsupported(_rule_text(rule)) from None
    return _Rule(freq, _number(rule, "INTERVAL", 1, 1, MAX_INTERVAL), _number(rule, "COUNT", None, 1), until,
                 weekdays, month_days)


def _month_days(year: int, month: int, weekdays: list[tuple[int, int]]) -> list[dt.date]:
    """BYDAY inside a month: '1MO' is the first Monday, '-1FR' the last Friday, 'WE' every Wednesday."""
    last = calendar.monthrange(year, month)[1]
    out: set[dt.date] = set()
    for n, wd in weekdays:
        days = [dt.date(year, month, d) for d in range(1, last + 1) if dt.date(year, month, d).weekday() == wd]
        if n:
            idx = n - 1 if n > 0 else n
            if -len(days) <= idx < len(days):
                out.add(days[idx])
        else:
            out.update(days)
    return sorted(out)


def _periods(rule: _Rule, first_day: dt.date, near: dt.date | None) -> Iterator[tuple[dt.date, list[dt.date]]]:
    """(first day of a period, the days in it the rule names), period after period: days, weeks, months or years.

    A period with no day in it is still handed over, empty, so the caller can count it and stop: a rule such as
    "the 31st, every 12 months from April" names no day at all. Ends at the last date the calendar can hold.
    `near` is where the caller starts to care; earlier periods are stepped over, never walked.
    """
    step = rule.interval
    try:
        if rule.freq == "DAILY":
            wanted = {wd for _, wd in rule.weekdays} or None
            day = first_day
            if near and near > day:
                day += dt.timedelta(days=max(0, (near - day).days // step - 1) * step)
            while True:
                yield day, ([day] if wanted is None or day.weekday() in wanted else [])
                day += dt.timedelta(days=step)
        elif rule.freq == "WEEKLY":
            days = sorted({wd for _, wd in rule.weekdays}) or [first_day.weekday()]
            week = first_day - dt.timedelta(days=first_day.weekday())
            if near and near > week:
                week += dt.timedelta(weeks=max(0, (near - week).days // 7 // step - 1) * step)
            while True:
                yield week, [week + dt.timedelta(days=wd) for wd in days]
                week += dt.timedelta(weeks=step)
        elif rule.freq == "MONTHLY":
            months = first_day.year * 12 + first_day.month - 1
            if near and near > first_day:
                months += max(0, (near.year * 12 + near.month - 1 - months) // step - 1) * step
            while True:
                year, month = months // 12, months % 12 + 1
                last = calendar.monthrange(year, month)[1]
                if rule.weekdays:
                    dates = _month_days(year, month, rule.weekdays)
                elif rule.month_days:
                    numbers = sorted({n if n > 0 else last + n + 1 for n in rule.month_days})
                    dates = [dt.date(year, month, n) for n in numbers if 1 <= n <= last]
                else:
                    dates = [dt.date(year, month, first_day.day)] if first_day.day <= last else []
                yield dt.date(year, month, 1), dates
                months += step
        else:  # YEARLY, on the same month and day
            year = first_day.year
            if near and near > first_day:
                year += max(0, (near.year - year) // step - 1) * step
            while True:
                try:
                    dates = [dt.date(year, first_day.month, first_day.day)]
                except ValueError:      # 29 February in a year without one
                    dates = []
                yield dt.date(year, 1, 1), dates
                year += step
    except (OverflowError, ValueError):     # past the year 9999
        return


def _starts(ev: Event, rule: _Rule, window_start: dt.datetime, window_end: dt.datetime) -> Iterator[dt.datetime]:
    """Occurrence starts in ascending order, without COUNT, UNTIL or EXDATE applied.

    Wall-clock time is kept across daylight-saving changes: a 09:30 meeting stays at 09:30.
    It always ends: when a period begins after the window, and, as a last resort, after `MAX_STEPS` periods.
    """
    start = ev.start
    tz, clock = start.tzinfo, start.time()
    # Without COUNT the early occurrences do not matter, so jump close to the window instead of walking years.
    near = window_start.astimezone(tz).date() if rule.count is None else None
    last_day = window_end.astimezone(tz).date()
    for steps, (period, days) in enumerate(_periods(rule, start.date(), near)):
        if period > last_day:
            return
        if steps > MAX_STEPS:
            raise Unsupported(_rule_text(ev.rrule or {}))
        for day in days:
            candidate = dt.datetime.combine(day, clock, tz)
            if candidate >= start:
                yield candidate


def _minute(t: dt.datetime) -> dt.datetime:
    return t.astimezone(UTC).replace(second=0, microsecond=0)


def expand(ev: Event, window_start: dt.datetime, window_end: dt.datetime) -> Iterator[tuple[dt.datetime, dt.datetime]]:
    """(start, end) of every occurrence that overlaps the window. Raises `Unsupported` for rules not expanded.

    An occurrence keeps the clock times of the first one, start and end, as calendars show it: 23:00 to 07:00
    stays 23:00 to 07:00 on the night the clocks change. Which occurrences fall in the window is decided in UTC,
    because two times in one zone compare by their clock reading, and that repeats when the clocks go back.
    """
    window_start, window_end = window_start.astimezone(UTC), window_end.astimezone(UTC)
    if not ev.rrule:
        if ev.start.astimezone(UTC) < window_end and ev.end.astimezone(UTC) > window_start:
            yield ev.start, ev.end
        return
    rule = _checked(ev)
    tz = ev.start.tzinfo
    if ev.end.tzinfo == tz:
        on_the_clock = ev.end.replace(tzinfo=None) - ev.start.replace(tzinfo=None)
        end_of = lambda s: (s.replace(tzinfo=None) + on_the_clock).replace(tzinfo=tz).astimezone(UTC)
    else:                           # it starts in one zone and ends in another: only real time can be kept
        length = ev.end.astimezone(UTC) - ev.start.astimezone(UTC)
        end_of = lambda s: s.astimezone(UTC) + length
    until = rule.until.astimezone(UTC) if rule.until is not None else None
    excluded = {_minute(x) for x in ev.exdates}
    produced = 0
    for local in _starts(ev, rule, window_start, window_end):
        start = local.astimezone(UTC)
        if until is not None and start > until:
            break
        if rule.count is not None and produced >= rule.count:
            break
        produced += 1               # COUNT includes occurrences that EXDATE later removes
        if start >= window_end:
            break
        try:
            end = end_of(local)
        except OverflowError:
            break
        if end > window_start and _minute(start) not in excluded:
            yield start.astimezone(tz), end.astimezone(tz)
