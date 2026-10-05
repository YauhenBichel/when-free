"""Where calendars come from: an address on the web or a file, read into events.

Every calendar or none: a calendar that silently fails to load would make busy time look free. Errors name the
calendar, never its address, because the address is a secret.

`load` takes the reader as an argument, so tests and other programs can supply calendars without the network.
"""
from __future__ import annotations

import pathlib
import urllib.error
import urllib.request
from collections.abc import Callable

from .. import __version__
from ..core import ical
from ..core.errors import Problem
from ..settings import Calendar

URL = ("http://", "https://", "webcal://")
NO_SLOTS = "No slots were printed, because without it busy time would look free."

Reader = Callable[[str], str]


def is_address(source: str) -> bool:
    return source.startswith(URL)


def read(source: str) -> str:
    """The text of a calendar at an address (webcal:// is read as https://) or in a file."""
    if is_address(source):
        url = "https://" + source[len("webcal://"):] if source.startswith("webcal://") else source
        req = urllib.request.Request(url, headers={"User-Agent": f"when-free/{__version__}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    return pathlib.Path(source).expanduser().read_text(encoding="utf-8", errors="replace")


def _hint(source: str, error: Exception) -> str:
    """What to try when an address is refused. It is built from the shape of the address and never quotes it."""
    if not is_address(source) or not isinstance(error, urllib.error.HTTPError) or not 400 <= error.code < 500:
        return ""
    if "calendar.google.com" in source and "/public/" in source:
        return (" This is the calendar's public address, which works only for a calendar made public."
                " Copy \"Secret address in iCal format\" instead.")
    return " Copy the address again from the calendar's settings: part of it may be missing."


def _check_is_calendar(name: str, text: str) -> None:
    if "BEGIN:VCALENDAR" in text:
        return
    if text.lstrip()[:200].lower().startswith(("<!doctype html", "<html")):
        raise Problem(f"the calendar '{name}' returned a web page, not a calendar; use the address that ends in .ics")
    raise Problem(f"the calendar '{name}' did not return iCalendar data; check its address")


def load(calendars: list[Calendar], tz, *, consequence: str = NO_SLOTS,
         reader: Reader | None = None) -> list[tuple[str, list[ical.Event]]]:
    """(name, events) for every calendar, or `Problem` naming the first one that could not be read."""
    reader = reader or read
    out = []
    for cal in calendars:
        try:
            text = reader(cal.source)
        except (OSError, urllib.error.URLError, ValueError) as e:
            reason = getattr(e, "reason", None) or getattr(e, "strerror", None) or e.__class__.__name__
            raise Problem(f"could not read the calendar '{cal.name}' ({reason}). {consequence}"
                          f"{_hint(cal.source, e)}") from None
        _check_is_calendar(cal.name, text)
        out.append((cal.name, ical.parse(text, tz)))
    return out
