"""Read the days and hours someone proposed out of ordinary text, by pattern matching.

"Wednesday 30th, Thursday 1st, between 10:00am and 4:00pm" -> two dates and (10:00, 16:00).
No model is involved here. Explicit dates win: "tomorrow", "Thursday" and "next week" are read only from text
that names no explicit date, so a heading like "Next week: Wednesday 30th" does not add a whole week.
"""
from __future__ import annotations

import datetime as dt
import re

from ..core.errors import clip

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_WD = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
# Whole names or the usual abbreviations only: "dec" must not match "decisions", nor "mon" "monitor".
_WEEKDAY = r"(?:mon(?:day)?|tue(?:s(?:day)?)?|wed(?:s|nesday)?|thu(?:r(?:s(?:day)?)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\.?"
_MONTH = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?"
          r"|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?")
_AMPM = r"(a\.?m\.?|p\.?m\.?)"
_N = r"(?:the\s+)?\d{1,2}(?:st|nd|rd|th)?"
_THROUGH = r"-|–|—|\bto\b|\bthrough\b|\bthru\b"                 # "2-4", "2 to 4": every day from one to the other
_JOIN = rf"\s*(?:,\s*(?:and|or)\b|,|&|\+|\band\b|\bor\b|{_THROUGH})\s*"
# A number that is an hour, not a day: "10:30", "3pm", "2-4pm".
_HOUR = rf"[:.]\d|\s*{_AMPM}(?![a-z])|\s*(?:-|–|—|to)\s*\d{{1,2}}(?:[:.]\d{{2}})?\s*{_AMPM}(?![a-z])"
_MORE = rf"(?:{_JOIN}{_N}\b(?!\d|/|{_HOUR}))"                   # one more day in a list: ", 3", " and 4th", "-6"
_YEAR = r"(?:,?\s+(?P<year>(?:19|20|21)\d{2})\b)?"


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


def _day_numbers(text: str, *, month_first: bool) -> list[int]:
    """The days in "2, 3 and 4" or "2-4". A range that runs backwards ("9-5") is hours, not days.

    After a month ("Dec 2, 9-5") the list ends at such a range. Before one ("9-5, 3 Dec") it starts after it.
    """
    out: list[int] = []
    through = False
    for number, joiner in re.findall(rf"(\d{{1,2}})|({_THROUGH})", text, re.I):
        if joiner:
            through = True
            continue
        n = int(number)
        if through and out:
            if out[-1] < n:
                out += range(out[-1] + 1, n + 1)
            elif month_first:
                return out[:-1]
            else:
                out = []
        else:
            out.append(n)
        through = False
    return out


def read_days(text: str, today: dt.date) -> tuple[list[dt.date], list[str]]:
    """Every explicit date in the text, sorted, and the parts that look like a date but were not read.

    Each stretch of text is read by one pattern only. The second list is there so that a caller can say
    "I did not read this part" instead of answering for fewer days than were asked about.
    """
    found: set[dt.date] = set()
    rest = text
    ends: list[int] = []                    # where a date that was read ends

    def take(pattern: str, build) -> None:
        """`build` gives the dates of a match and, when it does not use the whole match, where its part begins."""
        nonlocal rest
        for m in re.compile(pattern, re.I).finditer(rest):
            got, start = build(m)
            if got:
                found.update(got)
                ends.append(m.end())
                rest = rest[:start] + " " * (m.end() - start) + rest[m.end():]      # same length: positions hold

    def on(year: str | None, month: str, numbers: list[int]) -> list[dt.date]:
        out = []
        for n in numbers:
            try:
                d = dt.date(int(year), _MONTHS[month.lower()[:3]], n) if year else \
                    _nearest_year(_MONTHS[month.lower()[:3]], n, today)
            except ValueError:
                d = None
            if d:
                out.append(d)
        return out

    def iso(m):
        try:
            return [dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))], m.start()
        except ValueError:
            return [], m.start()

    def days_then_month(m):
        # "Oct 1, 5 Nov": the 1 belongs to October, so only the number next to the month is taken here.
        after_month = re.search(rf"\b{_MONTH}\s*$", rest[:m.start("days")], re.I)
        if after_month or not m.group("more"):
            start = m.start("last") if m.group("more") else m.start()
            return on(m.group("year"), m.group("month"), [int(re.search(r"\d+", m.group("last")).group())]), start
        return on(m.group("year"), m.group("month"), _day_numbers(m.group("days"), month_first=False)), m.start()

    def month_then_days(m):
        return on(m.group("year"), m.group("month"), _day_numbers(m.group("days"), month_first=True)), m.start()

    def weekday_day(m):
        if not m.group("ordinal") and re.match(rf"\s*(?:-|–|—|to\b)\s*\d|\s*{_AMPM}(?![a-z])", rest[m.end():], re.I):
            return [], m.start()                    # "Monday 9-5", "Friday 2pm": an hour, not the 9th or the 2nd
        n = int(m.group("day"))
        d = _nearest_weekday_day(_WD.index(m.group("weekday").lower()[:3]), n, today) if 1 <= n <= 31 else None
        return ([d] if d else []), m.start()

    take(r"\b(\d{4})-(\d{2})-(\d{2})\b", iso)
    # "1 October", "Thu 1 Oct", "Thursday the 1st of October", "2 and 3 December", "2-4 Dec", "14 Jan 2025"
    take(rf"(?:\b{_WEEKDAY},?\s+)?(?<![:.\d])(?P<days>(?P<more>(?:{_N}{_JOIN})*)(?P<last>{_N}))\s+(?:of\s+)?"
         rf"(?P<month>{_MONTH})(?![a-z]){_YEAR}", days_then_month)
    # "October 1st", "Thursday, October 1st", "Dec 2, 3, 4", "Dec 2-4", "Jan 14, 2025".
    # "May 2026" is a month and a year, not the 20th.
    take(rf"(?:\b{_WEEKDAY},?\s+)?\b(?P<month>{_MONTH})\s+(?P<days>{_N}\b(?!\d){_MORE}*){_YEAR}", month_then_days)
    # "Wednesday 30th", "Thu 1". "Friday 10:30" is a time, not the 10th.
    take(rf"\b(?P<weekday>{_WEEKDAY}),?\s+(?:the\s+)?(?P<day>\d{{1,2}})(?P<ordinal>st|nd|rd|th)?\b(?![:.]\d)", weekday_day)

    unread = [m.group().strip() for m in re.finditer(r"\b\d{1,2}(?:st|nd|rd|th)\b|(?<![\d/.:])\d{1,2}/\d{1,2}(?:/\d{2,4})?(?![\d/])", rest, re.I)]
    for end in ends:                                # "5 Oct, 7": the 7 is probably a day too
        m = re.compile(rf"{_JOIN}(\d{{1,2}})\b(?!\d|/|{_HOUR})", re.I).match(rest, end)
        if m and m.group(1) not in unread:
            unread.append(m.group(1))
    return sorted(found or relative_days(rest, today)), unread


def parse_days(text: str, today: dt.date) -> list[dt.date]:
    """Every explicit date in the text, sorted. See `read_days`."""
    return read_days(text, today)[0]


# Whole names only: a bare "sun" or "sat" is too often an ordinary word.
_NAMED_DAY = r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"


def relative_days(text: str, today: dt.date) -> set[dt.date]:
    """Days named relative to today: "tomorrow", "Thursday", "next Tuesday", "next week", "Tuesday next week".

    "Thursday" is the coming one (today, if today is Thursday). "next Thursday" is Thursday of next week, and
    "this Thursday" of this week. "last Thursday" is the one before today: a date in the past, which the caller
    reports as such. A week on its own means its working days, from today on.
    """
    t = text.lower()
    found: set[dt.date] = set()
    for phrase, offset in ((r"(?:the\s+)?day\s+after\s+tomorrow", 2), (r"tomorrow", 1), (r"today", 0)):
        if re.search(rf"\b{phrase}\b", t):
            found.add(today + dt.timedelta(days=offset))
            t = re.sub(rf"\b{phrase}\b", " ", t)
    monday = today - dt.timedelta(days=today.weekday())
    week = None
    if re.search(r"\b(?:the\s+)?week\s+after\s+next\b", t):
        week = 2
    elif re.search(r"\b(?:next|the\s+following|following|coming)\s+week\b", t):
        week = 1
    elif re.search(r"\bthis\s+week\b|\brest\s+of\s+the\s+week\b", t):
        week = 0
    named = False
    for m in re.finditer(rf"\b(?:(this|next|coming|last|previous)\s+)?{_NAMED_DAY}\b", t):
        named = True
        wd = _WD.index(m.group(2)[:3])
        if m.group(1) in ("last", "previous"):
            found.add(today - dt.timedelta(days=(today.weekday() - wd) % 7 or 7))
        elif week is not None:                            # "Tuesday or Wednesday next week"
            found.add(monday + dt.timedelta(weeks=week, days=wd))
        elif m.group(1) == "next":
            found.add(monday + dt.timedelta(weeks=1, days=wd))
        elif m.group(1) == "this":
            found.add(monday + dt.timedelta(days=wd))
        else:
            found.add(today + dt.timedelta(days=(wd - today.weekday()) % 7))
    if week is not None and not named:
        found |= {d for d in (monday + dt.timedelta(weeks=week, days=i) for i in range(5)) if d >= today}
    return found


def _clock(hour: int, minute: int, suffix: str | None) -> tuple[int, int]:
    suffix = (suffix or "").lower().replace(".", "")
    if suffix == "pm" and hour < 12:
        hour += 12
    if suffix == "am" and hour == 12:
        hour = 0
    return hour, minute


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
    # "any afternoon", "Friday morning". Several parts give the span from the first to the last.
    parts = [_PARTS[p.lower()] for p in re.findall(r"(?<!good )\b(morning|afternoon|evening)s?\b", text, re.I)]
    if parts:
        return dt.time(min(p[0] for p in parts)), dt.time(max(p[1] for p in parts))
    return None


_PARTS = {"morning": (9, 12), "afternoon": (12, 17), "evening": (17, 20)}


def hours_from_string(value: str) -> tuple[dt.time, dt.time]:
    """'09:00-18:00' from a flag or the settings file."""
    got = parse_hours(value)
    if not got:
        raise ValueError(f"cannot read hours from {clip(value)}; write them like 09:00-18:00")
    return got
