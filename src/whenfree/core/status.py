"""Where you stand right now: in an event or not, until when, and the next slot you could offer.

For status bars, busy lights, phones and smart homes. Event titles are never part of it.
"""
from __future__ import annotations

import datetime as dt

from . import slots

UTC = dt.timezone.utc       # every comparison is made in UTC: clock readings repeat when the clocks go back


def busy_until(busy: list[slots.Busy], now: dt.datetime) -> dt.datetime | None:
    """The end of the event you are in now, counting events that follow on without a gap. None if you are free."""
    end, now = None, now.astimezone(UTC)
    for start, finish in sorted((b.start.astimezone(UTC), b.end.astimezone(UTC)) for b in busy):
        if end is None:
            if start <= now < finish:
                end = finish
        elif start <= end:
            end = max(end, finish)
    return end


def free_until(busy: list[slots.Busy], now: dt.datetime, tz: dt.tzinfo) -> dt.datetime | None:
    """When the next event today starts, if you are free now. None if nothing else today."""
    midnight = dt.datetime.combine(now.astimezone(tz).date() + dt.timedelta(days=1), dt.time.min, tz).astimezone(UTC)
    now = now.astimezone(UTC)
    starts = [s for s in (b.start.astimezone(UTC) for b in busy) if now < s < midnight]
    return min(starts) if starts else None


def next_free(busy: list[slots.Busy] | slots.Timeline, now: dt.datetime, tz: dt.tzinfo, opens: dt.time, closes: dt.time, *,
              buffer_minutes: int, min_minutes: int, weekends: bool,
              horizon_days: int = 14) -> tuple[dt.datetime, dt.datetime] | None:
    """The first slot from now on, in working hours, at least `min_minutes` long."""
    today = now.astimezone(tz).date()
    for i in range(horizon_days):
        d = today + dt.timedelta(days=i)
        if not weekends and d.weekday() >= 5:
            continue
        found = slots.free_slots(d, opens, closes, busy, tz, buffer_minutes=buffer_minutes,
                                 min_minutes=min_minutes, now=now if i == 0 else None)
        if found:
            return found[0]
    return None


def status(busy: list[slots.Busy], now: dt.datetime, tz: dt.tzinfo, opens: dt.time, closes: dt.time, *,
           buffer_minutes: int, min_minutes: int, weekends: bool) -> dict:
    """Plain data: `free_now`, `busy_until` or `free_until`, `in_hours`, `next_free`, and what is left of `today`."""
    local = now.astimezone(tz)
    clock = lambda t: t.astimezone(tz).strftime("%H:%M")
    until = busy_until(busy, now)
    free_to = None if until else free_until(busy, now, tz)
    busy = slots.Timeline(busy)
    nxt = next_free(busy, now, tz, opens, closes, buffer_minutes=buffer_minutes, min_minutes=min_minutes,
                    weekends=weekends)
    working_day = weekends or local.weekday() < 5
    today = slots.free_slots(local.date(), opens, closes, busy, tz, buffer_minutes=buffer_minutes,
                             min_minutes=min_minutes, now=now) if working_day else []
    return {
        "now": local.isoformat(timespec="minutes"),
        "free_now": until is None,
        "busy_until": until.astimezone(tz).isoformat(timespec="minutes") if until else None,
        "free_until": free_to.astimezone(tz).isoformat(timespec="minutes") if free_to else None,
        "in_hours": working_day and opens <= local.time() < closes,
        "next_free": {"date": nxt[0].date().isoformat(), "start": clock(nxt[0]), "end": clock(nxt[1]),
                      "starts": nxt[0].isoformat(timespec="minutes")} if nxt else None,
        "today": [[clock(a), clock(b)] for a, b in today],
    }
