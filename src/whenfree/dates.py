"""Read the days and hours someone proposed out of ordinary text, by pattern matching.

"Wednesday 30th, Thursday 1st, between 10:00am and 4:00pm" -> two dates and (10:00, 16:00).
No model is involved here. It is deliberately modest: it reads explicit dates, never "next week".
"""
from __future__ import annotations

import datetime as dt
import re

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_WD = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
# Whole names or the usual abbreviations only: "dec" must not match "decisions", nor "mon" "monitor".
_WEEKDAY = r"(mon(?:day)?|tue(?:s(?:day)?)?|wed(?:s|nesday)?|thu(?:r(?:s(?:day)?)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\.?"
_MONTH = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?"
          r"|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?")
_DAY = r"(\d{1,2})(?:st|nd|rd|th)?"


def _nearest_year(month: int, day: int, today: dt.date) -> dt.date | None:
    best = None
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            d = dt.date(year, month, day)
        except ValueError:
            continue
        if best is None or abs((d - today).days) < abs((best - today).days):
            best = d
    return best


def _nearest_weekday_day(weekday: int, day: int, today: dt.date, reach: int = 200) -> dt.date | None:
    """The date nearest to today that is both this weekday and this day of the month.

    Nearest, not next: a message written last week that says "Wednesday 30th" means the Wednesday just gone,
    not one three months away. Past dates are dropped later, by the caller.
    """
    for offset in range(reach):
        for d in (today + dt.timedelta(days=offset), today - dt.timedelta(days=offset)):
            if d.day == day and d.weekday() == weekday:
                return d
    return None


def parse_days(text: str, today: dt.date) -> list[dt.date]:
    """Every explicit date in the text, sorted. Each stretch of text is read by one pattern only."""
    found: set[dt.date] = set()
    rest = text

    def take(pattern: str, build) -> None:
        nonlocal rest
        rx = re.compile(pattern, re.I)
        for m in rx.finditer(rest):
            try:
                d = build(m)
            except ValueError:
                d = None
            if d:
                found.add(d)
        rest = rx.sub(" ", rest)

    month = lambda s: _MONTHS[s.lower()[:3]]
    weekday = lambda s: _WD.index(s.lower()[:3])
    take(r"\b(\d{4})-(\d{2})-(\d{2})\b", lambda m: dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
    # "Thu 1 Oct", "Thursday the 1st of October"
    take(rf"\b{_WEEKDAY},?\s+(?:the\s+)?{_DAY}\s+(?:of\s+)?{_MONTH}\b",
         lambda m: _nearest_year(month(m.group(3)), int(m.group(2)), today))
    # "Thursday, October 1st"
    take(rf"\b{_WEEKDAY},?\s+{_MONTH}\s+{_DAY}\b(?!\d)",
         lambda m: _nearest_year(month(m.group(2)), int(m.group(3)), today))
    # "1 October", "1st of Oct"
    take(rf"\b{_DAY}\s+(?:of\s+)?{_MONTH}\b",
         lambda m: _nearest_year(month(m.group(2)), int(m.group(1)), today))
    # "October 1st". "May 2026" is a month and a year, not the 20th.
    take(rf"\b{_MONTH}\s+{_DAY}\b(?!\d)",
         lambda m: _nearest_year(month(m.group(1)), int(m.group(2)), today))
    # "Wednesday 30th", "Thu 1". "Friday 10:30" is a time, not the 10th.
    take(rf"\b{_WEEKDAY},?\s+(?:the\s+)?{_DAY}\b(?![:.]\d)",
         lambda m: _nearest_weekday_day(weekday(m.group(1)), int(m.group(2)), today)
         if 1 <= int(m.group(2)) <= 31 else None)
    return sorted(found)


def _clock(hour: int, minute: int, suffix: str | None) -> tuple[int, int]:
    suffix = (suffix or "").lower().replace(".", "")
    if suffix == "pm" and hour < 12:
        hour += 12
    if suffix == "am" and hour == 12:
        hour = 0
    return hour, minute


_AMPM = r"(a\.?m\.?|p\.?m\.?)"
_RANGE = re.compile(
    rf"\b(\d{{1,2}})(?:[:.](\d{{2}}))?\s*{_AMPM}?\s*(?:-|–|—|to|and|until|till)\s*(\d{{1,2}})(?:[:.](\d{{2}}))?\s*{_AMPM}?(?![\d:])",
    re.I)


def parse_hours(text: str) -> tuple[dt.time, dt.time] | None:
    """The first time range in the text: '10:00am and 4:00pm', '9-5pm', '10:00–16:00', '2 to 4 pm'."""
    for m in _RANGE.finditer(text):
        h1, m1, s1, h2, m2, s2 = m.groups()
        if not ((m1 is not None and m2 is not None) or s1 or s2):
            continue                                    # "5 and 6" alone is not a time range
        a = _clock(int(h1), int(m1 or 0), s1)
        b = _clock(int(h2), int(m2 or 0), s2)
        if not s1 and s2 and a[0] < 12 and (a[0] + 12, a[1]) < b:
            a = (a[0] + 12, a[1])                       # "2 to 4pm" is 14-16; "10 to 4pm" stays 10-16
        if not s1 and not s2 and b <= a and b[0] < 12:
            b = (b[0] + 12, b[1])                       # "10:00-4:00"
        if a[0] < 24 and b[0] < 24 and a[1] < 60 and b[1] < 60 and a < b:
            return dt.time(*a), dt.time(*b)
    return None


def hours_from_string(value: str) -> tuple[dt.time, dt.time]:
    """'09:00-18:00' from a flag or the settings file."""
    got = parse_hours(value)
    if not got:
        raise ValueError(f"cannot read hours from {value!r}; write them like 09:00-18:00")
    return got
