"""Your free slots as a calendar that phones, tablets and watches can subscribe to.

Every calendar app reads iCalendar over HTTP: Apple Calendar on iPhone, iPad, Mac and Watch, Google Calendar and
other Android apps, Outlook. Each free slot is an event called "Free", marked as free time so that it never blocks
anything itself. No event of yours appears in it, only the gaps between them.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

NAME = "Free (when-free)"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> list[str]:
    """Lines longer than 75 octets continue on the next line after a space (RFC 5545, 3.1)."""
    out, raw = [], line.encode()
    while len(raw) > 75:
        cut = 75 if not out else 74
        while cut and (raw[cut] & 0xC0) == 0x80:      # never split a UTF-8 character
            cut -= 1
        out.append(raw[:cut].decode())
        raw = raw[cut:]
    out.append(raw.decode())
    return [out[0]] + [" " + part for part in out[1:]]


def calendar(result: dict, *, host: str = "when-free", refresh_minutes: int = 15) -> str:
    """An iCalendar feed from `api.find_free`'s answer."""
    tz = ZoneInfo(result["timezone"])
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    utc = lambda day, clock: dt.datetime.combine(dt.date.fromisoformat(day), dt.time.fromisoformat(clock), tz) \
        .astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//when-free//free slots//EN", "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{NAME}", f"X-WR-TIMEZONE:{result['timezone']}",
        f"X-WR-CALDESC:{_escape('Times you could offer, from when-free. Updated every few minutes.')}",
        f"REFRESH-INTERVAL;VALUE=DURATION:PT{refresh_minutes}M", f"X-PUBLISHED-TTL:PT{refresh_minutes}M",
    ]
    for day in result["days"]:
        for start, end in day["free"]:
            lines += [
                "BEGIN:VEVENT",
                f"UID:{day['date']}-{start.replace(':', '')}-{end.replace(':', '')}@{host}",
                f"DTSTAMP:{stamp}",
                f"DTSTART:{utc(day['date'], start)}",
                f"DTEND:{utc(day['date'], end)}",
                "SUMMARY:Free",
                "TRANSP:TRANSPARENT",
                "END:VEVENT",
            ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(part for line in lines for part in _fold(line)) + "\r\n"
