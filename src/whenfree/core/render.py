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


def _hhmm(iso: str) -> str:
    return iso[11:16]


def _when(slot: dict, today: str) -> str:
    day = "" if slot["date"] == today else label(dt.date.fromisoformat(slot["date"])) + " "
    return f"{day}{slot['start']}–{slot['end']}"


def status_line(st: dict) -> str:
    """One short line for a status bar, a watch or a speaker: "Busy until 15:30 · next free 15:45–17:00"."""
    today = st["now"][:10]
    nxt = st["next_free"]
    if not st["free_now"]:
        head = f"Busy until {_hhmm(st['busy_until'])}"
    elif st["free_until"]:
        head = f"Free until {_hhmm(st['free_until'])}"
    else:
        head = "Free for the rest of the day"
    if nxt and (not st["free_now"] or not st["in_hours"]):
        return f"{head} · next free {_when(nxt, today)}"
    return head


def status_details(st: dict) -> list[str]:
    """A few lines under the status line: what is left of today, and the next slot."""
    today = st["now"][:10]
    out = ["Today: " + (", ".join(f"{a}–{b}" for a, b in st["today"]) or "no free slot left")]
    if st["next_free"]:
        out.append("Next free: " + _when(st["next_free"], today))
    return out
