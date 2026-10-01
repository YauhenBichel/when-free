"""From events to busy blocks, and from busy blocks to free slots."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from . import ical

UTC = dt.timezone.utc


@dataclass
class Busy:
    start: dt.datetime
    end: dt.datetime
    title: str = ""
    calendar: str = ""


def _declined(ev: ical.Event, me: list[str]) -> bool:
    mine = [m.lower() for m in me if m]
    return any(status == "DECLINED" and any(addr == f"mailto:{m}" or addr.endswith(m) for m in mine)
               for addr, status in ev.attendees)


def busy_blocks(events: list[ical.Event], window_start: dt.datetime, window_end: dt.datetime, *,
                me: list[str] | None = None, all_day_busy: bool = False, calendar: str = "",
                warnings: list[str] | None = None) -> list[Busy]:
    """What blocks time in the window.

    Not counted: events marked Free, cancelled events, invitations `me` declined, and whole-day events
    (unless `all_day_busy`). A recurring instance that was moved or edited is replaced by its override.
    """
    me = me or []
    overridden = {(e.uid, e.recurrence_id.astimezone(UTC)) for e in events if e.recurrence_id is not None}
    out: list[Busy] = []
    for ev in events:
        if ev.cancelled or ev.transparent or (ev.all_day and not all_day_busy) or _declined(ev, me):
            continue
        try:
            occurrences = list(ical.expand(ev, window_start, window_end))
        except ical.Unsupported as why:
            # Better to block one known date and say so than to guess the rest.
            if warnings is not None:
                warnings.append(f"'{ev.summary or 'untitled'}' repeats with a rule this tool does not expand ({why}); "
                                "only its first date is counted")
            occurrences = [(ev.start, ev.end)] if ev.start < window_end and ev.end > window_start else []
        for start, end in occurrences:
            if ev.rrule and (ev.uid, start.astimezone(UTC)) in overridden:
                continue
            if end > start:
                out.append(Busy(start, end, ev.summary, calendar))
    return sorted(out, key=lambda b: (b.start, b.end))


def _round_up(t: dt.datetime, minutes: int = 15) -> dt.datetime:
    t = t.replace(second=0, microsecond=0)
    extra = t.minute % minutes
    return t if extra == 0 and t.second == 0 else t + dt.timedelta(minutes=minutes - extra)


def free_slots(day: dt.date, opens: dt.time, closes: dt.time, busy: list[Busy], tz: dt.tzinfo, *,
               buffer_minutes: int = 15, min_minutes: int = 60,
               now: dt.datetime | None = None) -> list[tuple[dt.datetime, dt.datetime]]:
    """Free intervals on `day` between `opens` and `closes`, in `tz`.

    A buffer is kept on both sides of every busy block. If `now` falls inside the day, the day starts at the
    next quarter hour instead of in the past. Slots shorter than `min_minutes` are dropped last, after trimming.
    """
    lo = dt.datetime.combine(day, opens, tz)
    hi = dt.datetime.combine(day, closes, tz)
    if now is not None and now > lo:
        lo = max(lo, _round_up(now.astimezone(tz)))
    if lo >= hi:
        return []
    pad = dt.timedelta(minutes=buffer_minutes)
    blocks = sorted((max(b.start - pad, lo), min(b.end + pad, hi)) for b in busy
                    if b.start - pad < hi and b.end + pad > lo)
    free, cursor = [], lo
    for start, end in blocks:
        if start > cursor:
            free.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < hi:
        free.append((cursor, hi))
    need = dt.timedelta(minutes=min_minutes)
    # Busy blocks can be in any zone (UTC, the organiser's); the answer is always in the reader's.
    return [(a.astimezone(tz), b.astimezone(tz)) for a, b in free if b - a >= need]
