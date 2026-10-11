"""The services the MCP server can reach. Each one is its own component; this list is the only place they meet."""
from __future__ import annotations

from .. import drive, github, gmail, hubspot, linear, notion, outlook, slack, teams

MODULES = (gmail, drive, outlook, teams, slack, github, notion, linear, hubspot)


def accounts() -> list[str]:
    seen: list[str] = []
    for mod in MODULES:
        if mod.ACCOUNT not in seen:
            seen.append(mod.ACCOUNT)
    return seen
