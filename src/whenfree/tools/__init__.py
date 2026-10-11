"""The registry. This is the only module that imports the services. The MCP server calls what is collected here."""
from __future__ import annotations

from collections.abc import Callable

from ..core.errors import Problem
from . import accounts, calendar, signin
from . import drive, github, gmail, hubspot, linear, notion, outlook, slack, teams
from .model import Context, Tool

# Order is the order the server lists them. Calendars first, then one group per service.
MODULES = (gmail, drive, outlook, teams, slack, github, notion, linear, hubspot)

# `whenfree serve` is for calendars and phones. Mail and chat are MCP tools only.
HTTP_TOOLS = ("free_slots", "status", "check_calendars")


def _accounts() -> tuple[str, ...]:
    seen: list[str] = []
    for mod in MODULES:
        if mod.ACCOUNT not in seen:
            seen.append(mod.ACCOUNT)
    return tuple(seen)


ACCOUNTS = _accounts()


def _scopes(account: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(scope for mod in MODULES if mod.ACCOUNT == account for scope in mod.SCOPES))


def sign_in(account: str, config_path: str | None = None) -> str:
    """Sign in one account. The command calls this; the MCP server does not collect passwords."""
    return signin.sign_in(account, _scopes(account), config_path)


def _adapt(spec: dict, run: Callable) -> Tool:
    """A service runner takes a settings path. A tool takes the context the server passes."""
    def wrapped(arguments: dict, ctx: Context) -> tuple[str, dict]:
        return run(arguments, ctx.config_path)
    return Tool(spec, wrapped)


def _collect() -> list[Tool]:
    items = list(calendar.TOOLS)
    items.append(accounts.make(ACCOUNTS))
    for mod in MODULES:
        items.extend(_adapt(spec, run) for spec, run in mod.TOOLS)
    return items


REGISTRY: dict[str, Tool] = {item.name: item for item in _collect()}
TOOLS = [item.spec for item in REGISTRY.values()]


def get(name: str) -> Tool:
    found = REGISTRY.get(name)
    if found is None:
        raise Problem(f"unknown tool {name!r}. Known: {', '.join(REGISTRY)}")
    return found


def call(name: str, arguments: dict | None = None, *, config_path: str | None = None,
         reader: Callable[[str], str] | None = None) -> tuple[str, dict]:
    """Run a tool. Returns (text for the model, the same answer as data). Raises Problem."""
    found = get(name)
    arguments = arguments or {}
    found.validate(arguments)
    return found.run(arguments, Context(config_path, reader))


def openai_schema() -> list[dict]:
    return [{"type": "function", "function": {"name": item["name"], "description": item["description"], "parameters": item["inputSchema"]}}
            for item in TOOLS]
