"""`whenfree demo`: see what it does before giving it a calendar.

It makes up a calendar for next week, in your time zone, and answers a recruiter's message from it. Nothing is
read from your settings, nothing is fetched, nothing is saved.
"""
from __future__ import annotations

import datetime as dt
import os
from zoneinfo import ZoneInfo

from .. import api, settings
from ..core import render

MESSAGE = ("Hi! Thanks for applying. Could you share a few times on Tuesday, Wednesday or Thursday next week,\n"
           "between 10am and 4pm? The interview takes about an hour.")

# (weekday 0=Monday, start, end, title). A week someone might really have.
WEEK = [
    (1, "10:00", "11:30", "Design review"),
    (1, "13:00", "14:00", "Lunch with Sam"),
    (2, "11:00", "12:00", "Dentist"),
    (2, "14:30", "15:00", "Call with the bank"),
    (3, "09:00", "13:00", "Workshop"),
    (3, "15:00", "15:30", "One-to-one"),
    (4, "14:00", "15:00", "Team retro"),
]


def calendar(monday: dt.date, tz: str) -> str:
    """An iCalendar feed for the week starting `monday`: a daily standup and the events above."""
    stamp = lambda d, t: f"{d:%Y%m%d}T{t.replace(':', '')}00"
    events = [
        "BEGIN:VEVENT", "UID:standup@demo", f"DTSTART;TZID={tz}:{stamp(monday, '09:30')}",
        f"DTEND;TZID={tz}:{stamp(monday, '09:45')}", "RRULE:FREQ=DAILY;COUNT=5", "SUMMARY:Standup", "END:VEVENT",
    ]
    for i, (wd, start, end, title) in enumerate(WEEK):
        day = monday + dt.timedelta(days=wd)
        events += ["BEGIN:VEVENT", f"UID:{i}@demo", f"DTSTART;TZID={tz}:{stamp(day, start)}",
                   f"DTEND;TZID={tz}:{stamp(day, end)}", f"SUMMARY:{title}", "END:VEVENT"]
    return "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//when-free//demo//EN", *events, "END:VCALENDAR"]) + "\r\n"


def run(timezone: str | None = None) -> str:
    tz = timezone or settings.system_timezone()
    try:
        today = settings.now(ZoneInfo(tz)).date()
    except Exception:
        raise api.Problem(f"unknown time zone {tz!r}; use a name like Europe/London") from None
    monday = today + dt.timedelta(days=7 - today.weekday())
    feed = calendar(monday, tz)
    result = api.find_free(api.Query(message=MESSAGE, timezone=tz, calendars=["demo calendar"], config_path=os.devnull,
                                     use_extract=False), reader=lambda source: feed)
    quoted = "\n".join("  > " + line for line in MESSAGE.splitlines())
    busy = []
    for day in result["days"]:
        busy.append(f"  {day['label']}: " + ", ".join(f"{b['start']}–{b['end']} {b['title']}" for b in day["busy"]))
    return "\n".join([
        "when-free demo: a made-up calendar for next week, and this message:",
        "",
        quoted,
        "",
        "  $ pbpaste | whenfree --message -",
        "",
        "  " + render.header(result),
        *("  " + line for line in render.lines(result)),
        "",
        "What was in the calendar on those days (whenfree --busy shows this):",
        *busy,
        "",
        "Each slot keeps 15 minutes clear around events and is at least an hour long.",
        "",
        "Now with your own calendar:",
        "  whenfree add          paste your calendar's private iCal address; it is checked, then saved",
        "  whenfree              your free time over the next working days",
    ])
