"""From events to busy blocks, and from busy blocks to free slots."""
from __future__ import annotations

import datetime as dt
from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from . import ical

UTC = dt.timezone.utc


@dataclass
class Busy:
    start: dt.datetime
    end: dt.datetime
    title: str = ""
    calendar: str = ""


def _utc(t: dt.datetime) -> dt.datetime:
    return t.astimezone(UTC)


class Timeline:
    """Busy blocks in order, with an index, so that one day is found without reading the whole year.

    Python compares two times in the same zone by their clock reading, which is wrong on the day the clocks go
    back, so every comparison here is made in UTC.
    """

    def __init__(self, busy: list[Busy]):
        self.blocks = sorted(busy, key=lambda b: (_utc(b.start), _utc(b.end)))
        self._starts = [_utc(b.start) for b in self.blocks]
        self._reach: list[dt.datetime] = []             # the latest end among this block and all before it
        for b in self.blocks:
            end = _utc(b.end)
            self._reach.append(max(end, self._reach[-1]) if self._reach else end)

    def __len__(self) -> int:
        return len(self.blocks)

    def overlapping(self, start: dt.datetime, end: dt.datetime) -> list[Busy]:
        """Blocks that begin before `end` and finish after `start`, in order."""
        start, end = _utc(start), _utc(end)
        first = bisect_right(self._reach, start)        # nothing before it reaches past `start`
        stop = bisect_left(self._starts, end)
        return [b for b in self.blocks[first:stop] if _utc(b.end) > start]


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
    window_start, window_end = _utc(window_start), _utc(window_end)
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
            occurrences = [(ev.start, ev.end)] if _utc(ev.start) < window_end and _utc(ev.end) > window_start else []
        for start, end in occurrences:
            start, end = _utc(start), _utc(end)
            if ev.rrule and (ev.uid, start) in overridden:
                continue
            if end > start:
                out.append(Busy(start, end, ev.summary, calendar))
    return sorted(out, key=lambda b: (b.start, b.end))


def _round_up(t: dt.datetime, minutes: int = 15) -> dt.datetime:
    """The next quarter hour, or `t` itself when it is one. 10:15:01 is already past 10:15, so it gives 10:30."""
    t = _utc(t)
    floor = t.replace(minute=t.minute - t.minute % minutes, second=0, microsecond=0)
    return floor if floor == t else floor + dt.timedelta(minutes=minutes)


def free_slots(day: dt.date, opens: dt.time, closes: dt.time, busy: list[Busy] | Timeline, tz: dt.tzinfo, *,
               buffer_minutes: int = 15, min_minutes: int = 60,
               now: dt.datetime | None = None) -> list[tuple[dt.datetime, dt.datetime]]:
    """Free intervals on `day` between `opens` and `closes`, in `tz`.

    A buffer is kept on both sides of every busy block. If `now` falls inside the day, the day starts at the
    next quarter hour instead of in the past. Slots shorter than `min_minutes` are dropped last, after trimming.

    All of it is worked out in UTC, so a slot's length is real time on the days the clocks change. Hours that
    do not exist that day (01:30 when the clocks jump from 01:00 to 02:00) are read as the same time later.
    Pass a `Timeline` instead of a list when asking about many days.
    """
    lo = _utc(dt.datetime.combine(day, opens, tz))
    hi = _utc(dt.datetime.combine(day, closes, tz))
    if now is not None and _utc(now) > lo:
        lo = max(lo, _round_up(now))
    if lo >= hi:
        return []
    pad = dt.timedelta(minutes=buffer_minutes)
    near = busy.overlapping(lo - pad, hi + pad) if isinstance(busy, Timeline) else busy
    blocks = sorted((max(_utc(b.start) - pad, lo), min(_utc(b.end) + pad, hi)) for b in near
                    if _utc(b.start) - pad < hi and _utc(b.end) + pad > lo)
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
