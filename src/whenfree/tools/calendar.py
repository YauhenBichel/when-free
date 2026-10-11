"""The calendar tools. They read free time and never change a calendar."""
from __future__ import annotations

from .. import api
from ..core import render
from .model import Context, Tool

_FREE_SLOTS = {
    "name": "free_slots",
    "description": (
        "Find when the user is free. Reads the user's own calendars and returns, for each day asked about, "
        "the time ranges with no events, in the user's time zone. Use it when the user needs to offer, choose "
        "or confirm times for a meeting, call or interview. "
        "Say which days in one of three ways: `days` (explicit dates), `from` and `to` (a range), or `message` "
        "(text such as a recruiter's email, from which the days and a daily window are read). With none "
        "of them, the next working days are returned. "
        "It never guesses: if a calendar cannot be read it returns an error instead of slots, and days already "
        "past are listed under `past`. It only reads. It cannot create or change events."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "days": {"type": "string", "description": "Specific days, comma-separated. ISO dates are safest: \"2026-10-05, 2026-10-06\". Also understood: \"Thu 1 Oct, Fri 2 Oct\", \"tomorrow\", \"next week\"."},
            "from": {"type": "string", "description": "First day of a range, YYYY-MM-DD. Default: today."},
            "to": {"type": "string", "description": "Last day of a range, YYYY-MM-DD."},
            "message": {"type": "string", "description": "Text to read the proposed days and hours from, for example the email asking for availability. Explicit dates are read, and when there are none, phrases relative to today: \"tomorrow\", \"Thursday\", \"next Tuesday\", \"next week\", \"any afternoon\"."},
            "hours": {"type": "string", "description": "The part of the day to offer, HH:MM-HH:MM, for example \"10:00-16:00\", or \"morning\", \"afternoon\", \"evening\". Default: the user's configured hours."},
            "min_minutes": {"type": "integer", "minimum": 1, "description": "Shortest slot to return, in minutes. Set it to the meeting length. Default: the user's setting, usually 60."},
            "buffer_minutes": {"type": "integer", "minimum": 0, "description": "Time kept free before and after every event. Default: the user's setting, usually 15."},
            "timezone": {"type": "string", "description": "Time zone for the answer, like \"Europe/London\". Default: the user's zone."},
            "weekends": {"type": "boolean", "description": "Include Saturday and Sunday in a range. Default false."},
            "all_day_busy": {"type": "boolean", "description": "Treat whole-day events as busy. Default false."},
            "include_busy": {"type": "boolean", "description": "Also return what blocks each day, with event titles. Titles are private: ask only if the user wants to see them. Default false."},
        },
        "additionalProperties": False,
    },
}

_STATUS = {
    "name": "status",
    "description": ("Whether the user is free right now, until when, and their next free slot. Use it for "
                    "\"am I free now?\", \"when is my next gap?\" or before interrupting the user. Returns no event "
                    "titles."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "min_minutes": {"type": "integer", "minimum": 1, "description": "Shortest gap that counts as the next free slot. Default: the user's setting."},
            "timezone": {"type": "string", "description": "Time zone for the answer, like \"Europe/London\". Default: the user's zone."},
        },
        "additionalProperties": False,
    },
}

_CHECK = {
    "name": "check_calendars",
    "description": ("Check that the user's calendars can be read. Returns each calendar's name, how many events it "
                    "holds and how many block time in the next 14 days. Use it when free_slots fails or to confirm "
                    "the setup. Returns no event details and no calendar addresses."),
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
}


def _run_free_slots(arguments: dict, ctx: Context) -> tuple[str, dict]:
    show_busy = bool(arguments.get("include_busy"))
    result = api.find_free(api.Query(
        days=arguments.get("days"), start=arguments.get("from"), end=arguments.get("to"),
        message=arguments.get("message"), hours=arguments.get("hours"),
        min_minutes=arguments.get("min_minutes"), buffer_minutes=arguments.get("buffer_minutes"),
        timezone=arguments.get("timezone"), weekends=bool(arguments.get("weekends")),
        all_day_busy=bool(arguments.get("all_day_busy")), config_path=ctx.config_path), reader=ctx.reader)
    if not show_busy:
        for day in result["days"]:
            del day["busy"]
    return render.answer(result, busy=show_busy), result


def _run_check(arguments: dict, ctx: Context) -> tuple[str, dict]:
    data = api.check_calendars(config_path=ctx.config_path, reader=ctx.reader)
    return "\n".join([f"Time zone: {data['timezone']}"] + render.calendars_checked(data)), data


def _run_status(arguments: dict, ctx: Context) -> tuple[str, dict]:
    data = api.status(config_path=ctx.config_path, timezone=arguments.get("timezone"),
                      min_minutes=arguments.get("min_minutes"), reader=ctx.reader)
    return "\n".join([render.status_line(data), *render.status_details(data)]), data


TOOLS = [Tool(_FREE_SLOTS, _run_free_slots), Tool(_STATUS, _run_status), Tool(_CHECK, _run_check)]
