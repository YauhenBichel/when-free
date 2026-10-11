"""The tool registry the MCP server uses. Adding a service means importing its tools here, not teaching the server about it."""
from __future__ import annotations

from collections.abc import Callable

from ..core.errors import Problem
from . import accounts, calendar
from .model import Context, Tool
from .services import MODULES

# The HTTP server (`whenfree serve`) is for calendars and phones. Mail and chat are MCP tools only.
HTTP_TOOLS = ("free_slots", "status", "check_calendars")


def _bind(spec: dict, run: Callable) -> Tool:
    def wrapped(arguments: dict, ctx: Context) -> tuple[str, dict]:
        return run(arguments, ctx.config_path)
    return Tool(spec, wrapped)


def _all() -> list[Tool]:
    items = list(calendar.TOOLS)
    items.append(accounts.TOOL)
    for mod in MODULES:
        items.extend(_bind(spec, run) for spec, run in mod.TOOLS)
    return items


REGISTRY: dict[str, Tool] = {item.name: item for item in _all()}
TOOLS = [item.spec for item in REGISTRY.values()]


def get(name: str) -> Tool:
    tool = REGISTRY.get(name)
    if tool is None:
        raise Problem(f"unknown tool {name!r}. Known: {', '.join(REGISTRY)}")
    return tool


def call(name: str, arguments: dict | None = None, *, config_path: str | None = None,
         reader: Callable[[str], str] | None = None) -> tuple[str, dict]:
    """Run a tool. Returns (text for the model, the same answer as data). Raises Problem."""
    tool = get(name)
    arguments = arguments or {}
    tool.validate(arguments)
    return tool.run(arguments, Context(config_path, reader))


def openai_schema() -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["inputSchema"]}}
            for t in TOOLS]
