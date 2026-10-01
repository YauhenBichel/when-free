"""The whenfree command."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

from . import __version__, config as settings, dates, extract, ical, slots

COMMANDS = ("slots", "init", "check")
DAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

SETUP_HINT = """No calendar is configured.

  whenfree init          creates the settings file and tells you where it is
  then paste your calendar's private iCal address into it

Or try it once without a settings file:

  whenfree --calendar https://calendar.google.com/calendar/ical/.../basic.ics
  whenfree --calendar ~/Downloads/calendar.ics"""


class Problem(Exception):
    """Something the user can fix. Printed without a traceback."""


def _read(source: str) -> str:
    if source.startswith(("http://", "https://", "webcal://")):
        url = "https://" + source[len("webcal://"):] if source.startswith("webcal://") else source
        req = urllib.request.Request(url, headers={"User-Agent": f"when-free/{__version__}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    return pathlib.Path(source).expanduser().read_text(encoding="utf-8", errors="replace")


def _calendars(args, cfg: settings.Config) -> list[settings.Calendar]:
    if getattr(args, "calendar", None):
        return [settings.Calendar(f"calendar {i}", s) for i, s in enumerate(args.calendar, 1)]
    return cfg.calendars


def _load(calendars: list[settings.Calendar], tz) -> list[tuple[str, list[ical.Event]]]:
    """Every calendar or none: a calendar that silently fails to load would make busy time look free."""
    out = []
    for cal in calendars:
        try:
            text = _read(cal.source)
        except (OSError, urllib.error.URLError, ValueError) as e:
            # The address is a secret; name the calendar, never print where it lives.
            reason = getattr(e, "reason", None) or getattr(e, "strerror", None) or e.__class__.__name__
            raise Problem(f"could not read the calendar '{cal.name}' ({reason}). No slots were printed, "
                          "because without it busy time would look free.") from None
        if "BEGIN:VCALENDAR" not in text:
            raise Problem(f"the calendar '{cal.name}' did not return iCalendar data; check its address")
        out.append((cal.name, ical.parse(text, tz)))
    return out


def _timezone(args, cfg: settings.Config):
    name = getattr(args, "tz", None) or cfg.timezone or settings.system_timezone()
    try:
        return ZoneInfo(name)
    except Exception:
        raise Problem(f"unknown time zone {name!r}; use a name like Europe/London") from None


def _working_days(start: dt.date, count: int, weekends: bool) -> list[dt.date]:
    days, d = [], start
    while len(days) < count:
        if weekends or d.weekday() < 5:
            days.append(d)
        d += dt.timedelta(days=1)
    return days


def cmd_slots(args) -> int:
    cfg = settings.load(args.config)
    tz = _timezone(args, cfg)
    now = settings.now(tz)
    today = now.date()
    min_minutes = args.min if args.min is not None else cfg.min_minutes
    buffer_minutes = args.buffer if args.buffer is not None else cfg.buffer_minutes
    weekends = args.weekends or cfg.weekends
    hours = dates.hours_from_string(args.hours) if args.hours else None
    how = None

    if args.message:
        text = sys.stdin.read() if args.message == "-" else pathlib.Path(args.message).expanduser().read_text()
        got = None
        if cfg.extract_command and not args.no_extract:
            got = extract.run(cfg.extract_command, text, today)
        if got:
            days, how = got["days"], "by your model"
            if hours is None and got["hours"]:
                try:
                    hours = dates.hours_from_string(got["hours"])
                except ValueError:
                    pass
            if args.min is None and got["minutes"]:
                min_minutes = got["minutes"]
        else:
            days, how = dates.parse_days(text, today), "by pattern matching"
            if hours is None:
                hours = dates.parse_hours(text)
        if not days:
            raise Problem("found no dates in the message. Give them yourself: --days \"Thu 1 Oct, Fri 2 Oct\"")
    elif args.days:
        days = dates.parse_days(args.days, today)
        if not days:
            raise Problem(f"could not read any date from {args.days!r}. Examples: \"Thu 1 Oct, 5 Oct\" or 2026-10-05")
    else:
        try:
            first = dt.date.fromisoformat(args.start) if args.start else today
            last = dt.date.fromisoformat(args.end) if args.end else None
        except ValueError:
            raise Problem("--from and --to take dates like 2026-10-05") from None
        if last is None:
            days = _working_days(first, cfg.days_ahead, weekends)
        else:
            if last < first:
                raise Problem("--to is before --from")
            days = [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]
            days = [d for d in days if weekends or d.weekday() < 5]

    past = [d for d in days if d < today]
    days = [d for d in days if d >= today]
    if not days:
        raise Problem("every date asked for is already in the past")
    opens, closes = hours or dates.hours_from_string(cfg.hours)

    calendars = _calendars(args, cfg)
    if not calendars:
        raise Problem(SETUP_HINT)
    window_start = dt.datetime.combine(min(days), dt.time.min, tz)
    window_end = dt.datetime.combine(max(days) + dt.timedelta(days=1), dt.time.min, tz)
    warnings: list[str] = []
    busy: list[slots.Busy] = []
    total_events = 0
    for name, events in _load(calendars, tz):
        total_events += len(events)
        busy += slots.busy_blocks(events, window_start, window_end, me=cfg.me,
                                  all_day_busy=args.all_day_busy or cfg.all_day_busy, calendar=name, warnings=warnings)
    busy.sort(key=lambda b: (b.start, b.end))

    clock = lambda t: t.strftime("%H:%M")
    result = []
    for d in days:
        free = slots.free_slots(d, opens, closes, busy, tz, buffer_minutes=buffer_minutes,
                                min_minutes=min_minutes, now=now if d == today else None)
        day_start = dt.datetime.combine(d, dt.time.min, tz)
        blocking = [b for b in busy if b.start < day_start + dt.timedelta(days=1) and b.end > day_start]
        result.append((d, free, blocking))

    if args.format == "json":
        print(json.dumps({
            "timezone": tz.key, "hours": [clock(opens), clock(closes)], "min_minutes": min_minutes,
            "buffer_minutes": buffer_minutes,
            "days": [{"date": d.isoformat(), "free": [[clock(a), clock(b)] for a, b in free]} for d, free, _ in result],
        }, indent=2))
    else:
        # The context goes to stderr so that `whenfree | pbcopy` copies only the lines you paste into a reply.
        print(f"Free between {clock(opens)} and {clock(closes)} ({tz.key}), slots of {min_minutes}+ minutes, "
              f"{buffer_minutes}-minute buffer around events:\n", file=sys.stderr)
        for d, free, blocking in result:
            label = f"{DAY[d.weekday()]} {d.day} {d.strftime('%b')}"
            print(f"- {label}: " + (", ".join(f"{clock(a)}–{clock(b)}" for a, b in free) if free else "no free slot"))
            if args.busy:
                for b in blocking:
                    where = f"  [{b.calendar}]" if len(calendars) > 1 else ""
                    print(f"      busy {clock(b.start.astimezone(tz))}–{clock(b.end.astimezone(tz))}  {b.title or 'untitled'}{where}")
    if how:
        print(f"\nDates and hours were read from the message {how}. Check them against the message.", file=sys.stderr)
    if past:
        print(f"Left out, already past: {', '.join(f'{DAY[d.weekday()]} {d.day} {d:%b}' for d in past)}.", file=sys.stderr)
    for w in warnings:
        print(f"note: {w}", file=sys.stderr)
    print(f"{total_events} events read from {len(calendars)} calendar(s); {len(busy)} block time on these days.", file=sys.stderr)
    return 0


def cmd_init(args) -> int:
    path = settings.write_template(pathlib.Path(args.config).expanduser() if args.config else None)
    print(f"Created {path}\n\nOpen it and paste your calendar's private iCal address into the url line.\n"
          "Where to find it:\n"
          "  Google Calendar: Settings, your calendar, Integrate calendar, \"Secret address in iCal format\"\n"
          "  Outlook: Settings, Calendar, Shared calendars, Publish a calendar, the ICS link\n\n"
          "Then run: whenfree check")
    return 0


def cmd_check(args) -> int:
    cfg = settings.load(args.config)
    tz = _timezone(args, cfg)
    calendars = _calendars(args, cfg)
    if not calendars:
        raise Problem(SETUP_HINT)
    now = settings.now(tz)
    horizon = now + dt.timedelta(days=14)
    print(f"Settings: {cfg.path if cfg.path and cfg.path.exists() else 'none (defaults)'}   time zone: {tz.key}")
    for name, events in _load(calendars, tz):
        blocks = slots.busy_blocks(events, now, horizon, me=cfg.me, all_day_busy=cfg.all_day_busy)
        print(f"  ok  {name}: {len(events)} events, {len(blocks)} block time in the next 14 days")
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="whenfree", description="Which days and times am I free? Read from your calendar feeds, on your own machine.")
    p.add_argument("--version", action="version", version=f"when-free {__version__}")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("slots", help="print free slots (this is the default command)",
                       description="Print free slots. Without dates: the next working days.")
    s.add_argument("--from", dest="start", metavar="DATE", help="first day, like 2026-10-05 (default: today)")
    s.add_argument("--to", dest="end", metavar="DATE", help="last day, like 2026-10-09")
    s.add_argument("--days", metavar="TEXT", help='specific days: "Thu 1 Oct, Fri 2 Oct" or "2026-10-05, 2026-10-06"')
    s.add_argument("--message", metavar="FILE", help="read the proposed days and hours from a message; - reads standard input")
    s.add_argument("--hours", metavar="HH:MM-HH:MM", help="the part of the day to offer (default from settings: 09:00-18:00)")
    s.add_argument("--min", type=int, metavar="MINUTES", help="shortest slot to show")
    s.add_argument("--buffer", type=int, metavar="MINUTES", help="time kept free before and after every event")
    s.add_argument("--tz", metavar="ZONE", help="time zone for the answer, like Europe/London")
    s.add_argument("--weekends", action="store_true", help="include Saturdays and Sundays in a date range")
    s.add_argument("--all-day-busy", action="store_true", help="whole-day events block the day unless marked Free")
    s.add_argument("--busy", action="store_true", help="also list what blocks each day, with titles")
    s.add_argument("--format", choices=("text", "json"), default="text")
    s.add_argument("--no-extract", action="store_true", help="do not run the [extract] command; read dates by pattern matching")
    for x in (s,):
        x.add_argument("--calendar", action="append", metavar="ADDRESS_OR_FILE", help="use this calendar instead of the configured ones; repeatable")
        x.add_argument("--config", metavar="FILE", help="settings file (default: ~/.config/when-free/config.toml)")

    i = sub.add_parser("init", help="create the settings file")
    i.add_argument("--config", metavar="FILE")

    c = sub.add_parser("check", help="read every configured calendar and say what was found")
    c.add_argument("--calendar", action="append", metavar="ADDRESS_OR_FILE")
    c.add_argument("--config", metavar="FILE")
    c.add_argument("--tz", metavar="ZONE")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in COMMANDS and argv[0] not in ("-h", "--help", "--version")):
        argv = ["slots"] + argv
    args = _parser().parse_args(argv)
    try:
        return {"slots": cmd_slots, "init": cmd_init, "check": cmd_check}[args.command](args)
    except (Problem, settings.ConfigError, ValueError) as e:
        print(f"whenfree: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
