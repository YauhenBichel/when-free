"""A Model Context Protocol server over standard input and output. Standard library only.

    whenfree mcp

One JSON-RPC message per line in, one per line out. Only tools are offered. Nothing but protocol messages
is ever written to standard output; anything for a person goes to standard error.
"""
from __future__ import annotations

import io
import json
import sys

from . import __version__, tools
from .core.errors import Problem

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")       # newest first

INSTRUCTIONS = (
    "when-free finds the time slots the user can offer. It only offers tools. "
    "Collect the request with tools, then answer with tools. "
    "Read a mail or chat message with gmail_search, gmail_read, outlook_search, outlook_read, "
    "slack_history or teams_history when that is where the request is. "
    "Pass that text to free_slots as message, or pass days, from and to when the dates are already known. "
    "free_slots reads the calendars and returns the open slots. It never changes them. "
    "status answers whether the user is free right now. "
    "Give the user only slots a tool returned. If a tool returns an error, say what it says. Do not guess. "
    "To hand the slots back, use gmail_draft or outlook_draft. Those save a draft and do not send it. "
    "slack_post and teams_post send, so use them only when the user asked to post the slots. "
    "Do not look for a calendar in mail or chat. Calendars are read only by free_slots, status and check_calendars. "
    "If a tool says a service is not connected, tell the user to run whenfree connect for it."
)


def _result(id_, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _error(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _initialize(params: dict, config_path: str | None) -> dict:
    asked = params.get("protocolVersion")
    return {
        "protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": "when-free", "version": __version__},
        "instructions": INSTRUCTIONS,
    }


def _tools_list(params: dict, config_path: str | None) -> dict:
    return {"tools": tools.TOOLS}


def _tools_call(params: dict, config_path: str | None) -> dict:
    name, arguments = params.get("name"), params.get("arguments") or {}
    try:
        text, data = tools.call(name, arguments, config_path=config_path)
    except Problem as e:
        # A tool that could not do its job is a result the model can read and act on, not a protocol error.
        return {"content": [{"type": "text", "text": tools.short(str(e))}], "isError": True}
    except Exception as e:                            # never take the server down, never leak a traceback
        return {"content": [{"type": "text", "text": f"when-free failed: {e.__class__.__name__}"}], "isError": True}
    return {"content": [{"type": "text", "text": text}], "structuredContent": data, "isError": False}


METHODS = {
    "initialize": _initialize,
    "ping": lambda params, config_path: {},
    "tools/list": _tools_list,
    "tools/call": _tools_call,
}


def handle(message, config_path: str | None = None) -> dict | None:
    """Answer one message. Notifications (no id) get no answer."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
        return _error(message.get("id") if isinstance(message, dict) else None, -32600, "not a JSON-RPC 2.0 request")
    if "id" not in message:
        return None                                   # notifications/initialized, notifications/cancelled, ...
    method, id_ = message["method"], message["id"]
    if not (id_ is None or isinstance(id_, (str, int, float))) or isinstance(id_, bool):
        return _error(None, -32600, "the id must be a string or a number")
    if not isinstance(method, str):
        return _error(id_, -32600, "the method must be a string")
    answer = METHODS.get(method)
    if answer is None:
        return _error(id_, -32601, f"method not found: {method[:80]}")
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return _error(id_, -32602, "params must be an object")
    if method == "tools/call" and not isinstance(params.get("name"), str):
        return _error(id_, -32602, "params.name must be the name of a tool")
    return _result(id_, answer(params, config_path))


def _answer(line: str, config_path: str | None) -> dict | None:
    """The answer to one line. Whatever the line holds, this gives an answer or None; it does not raise."""
    try:
        message = json.loads(line)
    except RecursionError:                            # brackets nested thousands deep
        return _error(None, -32600, "the request is nested too deep to read")
    except ValueError:
        return _error(None, -32700, "parse error")
    try:
        return handle(message, config_path)
    except Exception as e:                            # one bad message must not end the session
        id_ = message.get("id") if isinstance(message, dict) else None
        return _error(id_ if isinstance(id_, (str, int, float)) else None, -32603,
                      f"when-free failed: {e.__class__.__name__}")


def serve(stdin=None, stdout=None, config_path: str | None = None) -> int:
    """Answer until standard input closes. A message it cannot read gets an error back; the server stays up."""
    if stdin is None:                                 # bytes that are not UTF-8 become a parse error, not a crash
        stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        answer = _answer(line, config_path)
        if answer is None:
            continue
        try:
            try:
                stdout.write(json.dumps(answer, ensure_ascii=False) + "\n")
            except UnicodeEncodeError:                # half a surrogate pair, echoed from the request
                stdout.write(json.dumps(answer) + "\n")
            stdout.flush()
        except BrokenPipeError:                       # the client went away
            return 0
    return 0
