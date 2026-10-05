"""The tools an agent can call, described once and offered four ways.

- the MCP server (`whenfree mcp`) lists and runs them
- `whenfree schema` prints them for function-calling harnesses (MCP shape or OpenAI shape)
- `whenfree call NAME` runs one from a shell, JSON in and JSON out
- `whenfree serve` offers them over local HTTP

Adding a tool is one entry in REGISTRY: its description for the model and the function that runs it.

Event titles are private. A tool leaves them out unless the caller asks with `include_busy`.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from . import api, render

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

_CHECK = {
    "name": "check_calendars",
    "description": ("Check that the user's calendars can be read. Returns each calendar's name, how many events it "
                    "holds and how many block time in the next 14 days. Use it when free_slots fails or to confirm "
                    "the setup. Returns no event details and no calendar addresses."),
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
}

_TYPES = {"string": str, "integer": int, "boolean": bool}


@dataclass(frozen=True)
class Tool:
    """A tool: what it is called, how it is described to a model, and what runs it."""
    spec: dict
    run: Callable[[dict, str | None], tuple[str, dict]]       # (arguments, settings path) -> (text, data)

    @property
    def name(self) -> str:
        return self.spec["name"]

    @property
    def properties(self) -> dict:
        return self.spec["inputSchema"]["properties"]

    def validate(self, arguments: dict) -> None:
        if not isinstance(arguments, dict):
            raise api.Problem("arguments must be an object")
        for key, value in arguments.items():
            if key not in self.properties:
                raise api.Problem(f"unknown argument {key!r} for {self.name}. Known: {', '.join(self.properties) or 'none'}")
            kind = _TYPES[self.properties[key]["type"]]
            if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
                raise api.Problem(f"argument {key!r} should be {self.properties[key]['type']}")

    def coerce(self, pairs: list[tuple[str, str]]) -> dict:
        """Arguments that arrived as text (a query string) converted by the schema. Bad values stay text,
        so that `validate` says what is wrong."""
        out: dict = {}
        for key, value in pairs:
            kind = self.properties.get(key, {}).get("type")
            if kind == "integer":
                try:
                    out[key] = int(value)
                    continue
                except ValueError:
                    pass
            elif kind == "boolean":
                out[key] = value.lower() in ("1", "true", "yes", "on", "")
                continue
            out[key] = value
        return out


def _run_free_slots(arguments: dict, config_path: str | None) -> tuple[str, dict]:
    show_busy = bool(arguments.get("include_busy"))
    result = api.find_free(api.Query(
        days=arguments.get("days"), start=arguments.get("from"), end=arguments.get("to"),
        message=arguments.get("message"), hours=arguments.get("hours"),
        min_minutes=arguments.get("min_minutes"), buffer_minutes=arguments.get("buffer_minutes"),
        timezone=arguments.get("timezone"), weekends=bool(arguments.get("weekends")),
        all_day_busy=bool(arguments.get("all_day_busy")), config_path=config_path))
    if not show_busy:
        for day in result["days"]:
            del day["busy"]
    return render.answer(result, busy=show_busy), result


def _run_check(arguments: dict, config_path: str | None) -> tuple[str, dict]:
    data = api.check_calendars(config_path=config_path)
    return "\n".join([f"Time zone: {data['timezone']}"] + render.calendars_checked(data)), data


REGISTRY: dict[str, Tool] = {t.name: t for t in (Tool(_FREE_SLOTS, _run_free_slots), Tool(_CHECK, _run_check))}
TOOLS = [t.spec for t in REGISTRY.values()]


def get(name: str) -> Tool:
    tool = REGISTRY.get(name)
    if tool is None:
        raise api.Problem(f"unknown tool {name!r}. Known: {', '.join(REGISTRY)}")
    return tool


def call(name: str, arguments: dict | None = None, *, config_path: str | None = None) -> tuple[str, dict]:
    """Run a tool. Returns (text for a person or a model to read, the same answer as data). Raises api.Problem."""
    tool = get(name)
    arguments = arguments or {}
    tool.validate(arguments)
    return tool.run(arguments, config_path)


def openai_schema() -> list[dict]:
    """The same tools in the shape function-calling APIs expect."""
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["inputSchema"]}}
            for t in TOOLS]
