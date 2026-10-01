"""A Model Context Protocol server over standard input and output. Standard library only.

    whenfree mcp

One JSON-RPC message per line in, one per line out. Only tools are offered. Nothing but protocol messages
is ever written to standard output; anything for a person goes to standard error.
"""
from __future__ import annotations

import json
import sys

from . import __version__, api, tools

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")       # newest first

INSTRUCTIONS = ("Use free_slots to find when the user is free before proposing or confirming a time. "
                "It reads the user's calendars and never changes them. Pass explicit dates when you know them. "
                "If it returns an error, tell the user what it says: do not guess availability.")


def _result(id_, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _error(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def handle(message, config_path: str | None = None) -> dict | None:
    """Answer one message. Notifications (no id) get no answer."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
        return _error(message.get("id") if isinstance(message, dict) else None, -32600, "not a JSON-RPC 2.0 request")
    method, id_, params = message["method"], message.get("id"), message.get("params") or {}
    if "id" not in message:
        return None                                   # notifications/initialized, notifications/cancelled, ...

    if method == "initialize":
        asked = params.get("protocolVersion")
        return _result(id_, {
            "protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "when-free", "version": __version__},
            "instructions": INSTRUCTIONS,
        })
    if method == "ping":
        return _result(id_, {})
    if method == "tools/list":
        return _result(id_, {"tools": tools.TOOLS})
    if method == "tools/call":
        name, arguments = params.get("name"), params.get("arguments") or {}
        try:
            text, data = tools.call(name, arguments, config_path=config_path)
        except api.Problem as e:
            # A tool that could not do its job is a result the model can read and act on, not a protocol error.
            return _result(id_, {"content": [{"type": "text", "text": str(e)}], "isError": True})
        except Exception as e:                        # never take the server down, never leak a traceback
            return _result(id_, {"content": [{"type": "text", "text": f"when-free failed: {e.__class__.__name__}"}], "isError": True})
        return _result(id_, {"content": [{"type": "text", "text": text}], "structuredContent": data, "isError": False})
    return _error(id_, -32601, f"method not found: {method}")


def serve(stdin=None, stdout=None, config_path: str | None = None) -> int:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            answer = _error(None, -32700, "parse error")
        else:
            answer = handle(message, config_path)
        if answer is not None:
            stdout.write(json.dumps(answer, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0
