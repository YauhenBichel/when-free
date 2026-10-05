"""The whenfree command."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import pathlib
import sys

from . import __version__, api, mcp, render, server, sources, tools
from . import config as settings


def cmd_slots(args) -> int:
    message = None
    if args.message:
        message = sys.stdin.read() if args.message == "-" else pathlib.Path(args.message).expanduser().read_text()
    result = api.find_free(api.Query(
        days=args.days, start=args.start, end=args.end, message=message, hours=args.hours,
        min_minutes=args.min, buffer_minutes=args.buffer, timezone=args.tz, weekends=args.weekends,
        all_day_busy=args.all_day_busy, calendars=args.calendar, config_path=args.config,
        use_extract=not args.no_extract))

    if args.format == "json":
        days = [{k: v for k, v in day.items() if k in ("date", "free") or (k == "busy" and args.busy)}
                for day in result["days"]]
        print(json.dumps({"timezone": result["timezone"], "hours": result["hours"], "min_minutes": result["min_minutes"],
                          "buffer_minutes": result["buffer_minutes"], "days": days}, indent=2, ensure_ascii=False))
    else:
        # The context goes to stderr so that `whenfree | pbcopy` copies only the lines you paste into a reply.
        print(render.header(result) + "\n", file=sys.stderr)
        for line in render.lines(result, busy=args.busy):
            print(line)
    notes = render.notes(result, past_as_labels=True)
    if notes:
        print("\n" + "\n".join(notes), file=sys.stderr)
    print(f"{result['events_read']} events read from {result['calendars']} calendar(s); "
          f"{result['blocking']} block time on these days.", file=sys.stderr)
    return 0


WHERE = """Where the private address of a calendar is:
  Google Calendar: Settings, your calendar, Integrate calendar, "Secret address in iCal format"
  Outlook: Settings, Calendar, Shared calendars, Publish a calendar, the ICS link
  iCloud: Calendar, the share icon next to the calendar, Public Calendar"""


def cmd_add(args) -> int:
    """Ask for one calendar, read it, and save it only if it could be read. The address is never shown."""
    source = args.file
    if source is None and sys.stdin.isatty():
        print(WHERE + "\n", file=sys.stderr)
        source = getpass.getpass("Paste the address and press Enter (it is not shown): ")
    elif source is None:
        source = sys.stdin.read()                    # pbpaste | whenfree add
    elif sources.is_address(source):
        print("note: an address given on the command line stays in your shell history. "
              "Next time run `whenfree add` and paste it when asked.", file=sys.stderr)
    source = source.strip().strip("\"'<>").strip()
    if not source or any(ord(ch) < 32 for ch in source) or (sources.is_address(source) and " " in source):
        raise api.Problem("that is not one address or one path. Copy the address again and paste only that.")
    if not (sources.is_address(source) or source.startswith("~")):
        source = os.path.abspath(source)             # a file is found again whatever folder the next run starts in
    found = api.add_calendar(source, name=args.name, config_path=args.config)
    print(f"Added '{found['name']}': {found['events']} events, {found['blocking_next_14_days']} block time in the next 14 days.")
    print(f"Saved in {found['settings']}, readable only by you. Now run: whenfree")
    if os.environ.get("WHENFREE_CALENDARS"):
        print("note: WHENFREE_CALENDARS is set and replaces the calendars in the settings file.", file=sys.stderr)
    return 0


def cmd_init(args) -> int:
    path = settings.write_template(pathlib.Path(args.config).expanduser() if args.config else None)
    print(f"Created {path}\n\nNow add a calendar:\n\n  whenfree add\n\n"
          "It asks for your calendar's private iCal address, checks it and saves it in that file.\n"
          "Or open the file and paste the address into the url line yourself.\n\n" + WHERE + "\n\n"
          "Then run: whenfree check")
    return 0


def cmd_check(args) -> int:
    data = api.check_calendars(config_path=args.config, calendars=args.calendar, timezone=args.tz)
    print(f"Settings: {data['settings'] or 'none (defaults)'}   time zone: {data['timezone']}")
    for line in render.calendars_checked(data):
        print("  " + line)
    return 0


def cmd_mcp(args) -> int:
    return mcp.serve(config_path=args.config)


def cmd_serve(args) -> int:
    return server.serve(args.host, args.port, config_path=args.config, origins=args.allow_origin)


def cmd_schema(args) -> int:
    print(json.dumps(tools.openai_schema() if args.format == "openai" else tools.TOOLS, indent=2, ensure_ascii=False))
    return 0


def cmd_call(args) -> int:
    """Run one tool from a shell: JSON arguments in, JSON out. For harnesses that shell out instead of speaking MCP."""
    raw = args.args if args.args is not None else ("" if sys.stdin.isatty() else sys.stdin.read())
    try:
        arguments = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": f"the arguments are not JSON: {e.msg}"}))
        return 1
    try:
        text, data = tools.call(args.tool, arguments, config_path=args.config)
    except api.Problem as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "text": text, "data": data}, indent=2, ensure_ascii=False))
    return 0


COMMANDS = {"slots": cmd_slots, "add": cmd_add, "init": cmd_init, "check": cmd_check, "mcp": cmd_mcp,
            "serve": cmd_serve, "schema": cmd_schema, "call": cmd_call}


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="whenfree", description="Which days and times am I free? Read from your calendar feeds, on your own machine.")
    p.add_argument("--version", action="version", version=f"when-free {__version__}")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("slots", help="print free slots (this is the default command)",
                       description="Print free slots. Without dates: the next working days.")
    s.add_argument("--from", dest="start", metavar="DATE", help="first day, like 2026-10-05 (default: today)")
    s.add_argument("--to", dest="end", metavar="DATE", help="last day, like 2026-10-09")
    s.add_argument("--days", metavar="TEXT", help='specific days: "Thu 1 Oct, Fri 2 Oct", "2026-10-05, 2026-10-06", "tomorrow", "next week"')
    s.add_argument("--message", metavar="FILE", help="read the proposed days and hours from a message; - reads standard input")
    s.add_argument("--hours", metavar="HH:MM-HH:MM", help="the part of the day to offer, or morning, afternoon, evening (default from settings: 09:00-18:00)")
    s.add_argument("--min", type=int, metavar="MINUTES", help="shortest slot to show")
    s.add_argument("--buffer", type=int, metavar="MINUTES", help="time kept free before and after every event")
    s.add_argument("--tz", metavar="ZONE", help="time zone for the answer, like Europe/London")
    s.add_argument("--weekends", action="store_true", help="include Saturdays and Sundays in a date range")
    s.add_argument("--all-day-busy", action="store_true", help="whole-day events block the day unless marked Free")
    s.add_argument("--busy", action="store_true", help="also list what blocks each day, with titles")
    s.add_argument("--format", choices=("text", "json"), default="text")
    s.add_argument("--no-extract", action="store_true", help="do not run the [extract] command; read dates by pattern matching")
    s.add_argument("--calendar", action="append", metavar="ADDRESS_OR_FILE", help="use this calendar instead of the configured ones; repeatable")
    s.add_argument("--config", metavar="FILE", help="settings file (default: ~/.config/when-free/config.toml)")

    a = sub.add_parser("add", help="add a calendar: asks for its address, checks it and saves it",
                       description="Add a calendar to the settings file. Without FILE it asks for the calendar's private "
                                   "address at a prompt that does not show it, or reads it from standard input: "
                                   "pbpaste | whenfree add. Nothing is saved unless the calendar can be read.")
    a.add_argument("file", nargs="?", metavar="FILE", help="an exported .ics file, instead of an address")
    a.add_argument("--name", help="what to call it in messages (default: personal, then calendar 2, calendar 3)")
    a.add_argument("--config", metavar="FILE", help="settings file (default: ~/.config/when-free/config.toml)")

    i = sub.add_parser("init", help="create the settings file")
    i.add_argument("--config", metavar="FILE")

    c = sub.add_parser("check", help="read every configured calendar and say what was found")
    c.add_argument("--calendar", action="append", metavar="ADDRESS_OR_FILE")
    c.add_argument("--config", metavar="FILE")
    c.add_argument("--tz", metavar="ZONE")

    m = sub.add_parser("mcp", help="run as a Model Context Protocol server on standard input and output",
                       description="An MCP server for assistants and agents. It offers two tools: free_slots and check_calendars.")
    m.add_argument("--config", metavar="FILE")

    sv = sub.add_parser("serve", help="run a local HTTP server with an OpenAPI description, for tools that cannot start a command",
                        description="A local HTTP server: POST /free_slots and /check_calendars with JSON, or GET with a query "
                                    "string. The OpenAPI description is at /openapi.json. Every tool call needs the token, "
                                    "kept next to the settings file or taken from WHENFREE_TOKEN.")
    sv.add_argument("--port", type=int, default=server.PORT, help=f"default {server.PORT}")
    sv.add_argument("--host", default="127.0.0.1", help="default 127.0.0.1: this machine only")
    sv.add_argument("--allow-origin", action="append", metavar="ORIGIN", default=[],
                    help="let a web page from this origin call it, like http://localhost:3000; repeatable")
    sv.add_argument("--config", metavar="FILE")

    sc = sub.add_parser("schema", help="print the tool definitions for a function-calling harness")
    sc.add_argument("--format", choices=("mcp", "openai"), default="mcp", help="mcp: name, description, inputSchema. openai: type function, parameters")

    ca = sub.add_parser("call", help="run one tool: JSON arguments in, JSON out",
                        description="Run a tool from a shell. Example: whenfree call free_slots --args '{\"days\": \"2026-10-05\"}'")
    ca.add_argument("tool", help="free_slots or check_calendars")
    ca.add_argument("--args", metavar="JSON", help="the arguments as JSON; without it they are read from standard input")
    ca.add_argument("--config", metavar="FILE")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in COMMANDS and argv[0] not in ("-h", "--help", "--version")):
        argv = ["slots"] + argv                     # slots is the default command
    args = _parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except (api.Problem, settings.ConfigError, ValueError) as e:
        print(f"whenfree: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
