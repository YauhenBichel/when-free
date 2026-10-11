"""Which accounts are signed in. Names only: no tokens. The registry supplies the names."""
from __future__ import annotations

from .connect import store
from .connect.schema import tool
from .model import Context, Tool

_SPEC = tool(
    "connected_accounts",
    "Which services are signed in on this computer (Google, Microsoft, Slack, GitHub, Notion, Linear, HubSpot). "
    "No tokens. If one is not connected, tell the user to run whenfree connect for that service.",
    {},
)


def make(names: tuple[str, ...]) -> Tool:
    def run(arguments: dict, ctx: Context) -> tuple[str, dict]:
        rows = [{"account": name, "connected": store.exists(f"{name}-token.json", ctx.config_path)} for name in names]
        text = "\n".join(f"{row['account']}: {'connected' if row['connected'] else 'not connected'}" for row in rows)
        return text, {"accounts": rows}

    return Tool(_SPEC, run)
