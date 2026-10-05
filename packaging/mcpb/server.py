"""Entry point of the Claude Desktop extension: the when-free MCP server, from the copy bundled next to this file."""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))

# An optional setting left empty may arrive as "" or, in some hosts, as the unreplaced placeholder.
# Either way it means "not set", so the settings file from `whenfree add` is used instead.
for name in ("WHENFREE_CALENDARS", "WHENFREE_TZ"):
    if os.environ.get(name, "").strip().startswith("${") or not os.environ.get(name, "").strip():
        os.environ.pop(name, None)

from whenfree.agents import mcp  # noqa: E402

sys.exit(mcp.serve())
