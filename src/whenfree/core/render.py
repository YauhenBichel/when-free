"""The answer as text for a person or a model. Every front end (command line, tools, HTTP) words it the same way."""
from __future__ import annotations

import datetime as dt

DAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def label(d: dt.date) -> str:
    return f"{DAY[d.weekday()]} {d.day} {d.strftime('%b')}"


def header(result: dict) -> str:
    return (f"Free between {result['hours'][0]} and {result['hours'][1]} ({result['timezone']}), "
            f"slots of {result['min_minutes']}+ minutes, {result['buffer_minutes']}-minute buffer around events:")


def lines(result: dict, busy: bool = False) -> list[str]:
    """One line per day, ready to paste into a reply. With `busy`, what blocks each day under it."""
    out = []
    for day in result["days"]:
        free = ", ".join(f"{a}–{b}" for a, b in day["free"]) or "no free slot"
        out.append(f"- {day['label']}: {free}")
        if busy:
            for b in day.get("busy", []):
                where = f"  [{b['calendar']}]" if result["calendars"] > 1 else ""
                out.append(f"      busy {b['start']}–{b['end']}  {b['title']}{where}")
    return out


def notes(result: dict, *, past_as_labels: bool = False) -> list[str]:
    """What the reader should know besides the slots: how dates were read, days left out, rules not expanded."""
    out = []
    if result["read_by"]:
        out.append(f"Dates and hours were read from the message by {result['read_by']}. Check them against the message.")
    if result["past"]:
        past = [label(dt.date.fromisoformat(d)) if past_as_labels else d for d in result["past"]]
        out.append("Left out, already past: " + ", ".join(past) + ".")
    out += [f"Note: {n}" for n in result["notes"]]
    return out


def answer(result: dict, busy: bool = False) -> str:
    """The whole answer in one piece, for a model or a program."""
    tail = notes(result)
    return "\n".join([header(result), ""] + lines(result, busy) + ([""] + tail if tail else []))


def calendars_checked(data: dict) -> list[str]:
    return [f"ok  {c['name']}: {c['events']} events, {c['blocking_next_14_days']} block time in the next 14 days"
            for c in data["calendars"]]
