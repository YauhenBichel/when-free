"""A small HTTP server for tools that cannot start a command: Open WebUI, n8n, Shortcuts, Raycast, scripts.

    whenfree serve                     # http://127.0.0.1:8765, OpenAPI description at /openapi.json

The same two tools as the MCP server, one path each, with JSON in and JSON out. Standard library only.

It is for this machine. It listens on 127.0.0.1, every tool call needs the token (a web page in your browser
can reach 127.0.0.1 too), and a request whose Host is not this machine is refused, which stops a web page
from reaching it through a name that points here (DNS rebinding).
"""
from __future__ import annotations

import hmac
import json
import os
import pathlib
import secrets
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, api, config as settings, tools

PORT = 8765
MAX_BODY = 64 * 1024
LOCAL_NAMES = {"127.0.0.1", "localhost", "::1", "[::1]"}


def token_path(config_path: str | None = None) -> pathlib.Path:
    """The token lives next to the settings file, readable only by you."""
    base = pathlib.Path(config_path).expanduser() if config_path else settings.default_path()
    return base.parent / "token"


def load_token(config_path: str | None = None) -> tuple[str, str]:
    """(the token, where it came from). WHENFREE_TOKEN wins; otherwise one is made once and kept in a file."""
    if os.environ.get("WHENFREE_TOKEN"):
        return os.environ["WHENFREE_TOKEN"], "WHENFREE_TOKEN"
    path = token_path(config_path)
    if path.exists():
        token = path.read_text().strip()
        if token:
            return token, str(path)
    token = secrets.token_urlsafe(24)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token + "\n")
    return token, str(path)


def openapi(base_url: str) -> dict:
    """An OpenAPI 3.1 description built from the same tool definitions the MCP server lists."""
    answer = {"type": "object", "properties": {
        "ok": {"type": "boolean"},
        "text": {"type": "string", "description": "The answer as text, ready to read or paste."},
        "data": {"type": "object", "description": "The same answer as data."},
        "error": {"type": "string", "description": "Why it could not answer, when ok is false. Do not guess instead."},
    }}
    paths = {}
    for tool in tools.TOOLS:
        paths[f"/{tool['name']}"] = {"post": {
            "operationId": tool["name"],
            "summary": tool["description"].split(". ")[0] + ".",
            "description": tool["description"],
            "requestBody": {"required": False, "content": {"application/json": {"schema": tool["inputSchema"]}}},
            "responses": {
                "200": {"description": "The answer", "content": {"application/json": {"schema": answer}}},
                "400": {"description": "It could not answer; `error` says why", "content": {"application/json": {"schema": answer}}},
                "401": {"description": "Missing or wrong token"},
            },
        }}
    return {
        "openapi": "3.1.0",
        "info": {"title": "when-free", "version": __version__,
                 "description": "Which days and times is the user free? Reads the user's own calendars, never changes them."},
        "servers": [{"url": base_url}],
        "paths": paths,
        "components": {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}},
        "security": [{"bearer": []}],
    }


def _from_query(tool: dict, query: str) -> dict:
    """GET /free_slots?days=tomorrow&min_minutes=30: query strings are text, so convert by the schema."""
    props, out = tool["inputSchema"]["properties"], {}
    for key, value in urllib.parse.parse_qsl(query, keep_blank_values=True):
        kind = props.get(key, {}).get("type")
        if kind == "integer":
            try:
                value = int(value)
            except ValueError:
                pass                                   # left as text, so the tool says what is wrong
        elif kind == "boolean":
            value = value.lower() in ("1", "true", "yes", "on", "")
        out[key] = value
    return out


def make_handler(token: str, config_path: str | None, origins: list[str], base_url: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"when-free/{__version__}"
        sys_version = ""

        def log_message(self, fmt, *args):            # one short line per request, never the query or body
            sys.stderr.write(f"{self.command} {urllib.parse.urlsplit(self.path).path} {args[1] if len(args) > 1 else ''}\n")

        def _send(self, status: int, body: dict | None, extra: dict | None = None) -> None:
            data = b"" if body is None else json.dumps(body, ensure_ascii=False, indent=2).encode()
            self.send_response(status)
            if body is not None:
                self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            origin = self.headers.get("Origin")
            if origin and origin in origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _local_host(self) -> bool:
            host = (self.headers.get("Host") or "").strip().lower()       # "127.0.0.1:8765", "[::1]:8765"
            name = host[:host.find("]") + 1] if host.startswith("[") else host.split(":")[0]
            return name in LOCAL_NAMES or name == urllib.parse.urlsplit(base_url).hostname

        def _authorised(self) -> bool:
            got = self.headers.get("Authorization", "")
            return got.startswith("Bearer ") and hmac.compare_digest(got[7:].strip().encode(), token.encode())

        def _route(self, body: dict | None) -> None:
            if not self._local_host():
                return self._send(403, {"ok": False, "error": "this server answers only requests addressed to this machine"})
            url = urllib.parse.urlsplit(self.path)
            name = url.path.strip("/")
            if name in ("", "health"):
                return self._send(200, {"ok": True, "name": "when-free", "version": __version__,
                                        "openapi": f"{base_url}/openapi.json"})
            if name == "openapi.json":
                return self._send(200, openapi(base_url))
            tool = next((t for t in tools.TOOLS if t["name"] == name), None)
            if tool is None:
                return self._send(404, {"ok": False, "error": f"no such path. Tools: {', '.join('/' + t['name'] for t in tools.TOOLS)}"})
            if not self._authorised():
                return self._send(401, {"ok": False, "error": "send the token as: Authorization: Bearer <token>"},
                                  {"WWW-Authenticate": "Bearer"})
            arguments = body if body is not None else _from_query(tool, url.query)
            try:
                text, data = tools.call(name, arguments, config_path=config_path)
            except api.Problem as e:
                return self._send(400, {"ok": False, "error": str(e)})
            except Exception as e:                    # never a traceback, never an address
                return self._send(500, {"ok": False, "error": f"when-free failed: {e.__class__.__name__}"})
            self._send(200, {"ok": True, "text": text, "data": data})

        def do_GET(self):
            self._route(None)

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._send(413, {"ok": False, "error": "the request is too large"})
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw) if raw.strip() else {}
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                return self._send(400, {"ok": False, "error": f"the body is not JSON: {getattr(e, 'msg', e)}"})
            self._route(body)

        def do_OPTIONS(self):                         # a browser asking before a cross-origin call
            origin = self.headers.get("Origin")
            if origin not in origins:
                return self._send(403, None)
            self._send(204, None, {"Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                                   "Access-Control-Allow-Headers": "Authorization, Content-Type",
                                   "Access-Control-Max-Age": "600"})

    return Handler


def make_server(host: str = "127.0.0.1", port: int = PORT, token: str = "", config_path: str | None = None,
                origins: list[str] | None = None) -> ThreadingHTTPServer:
    shown = f"[{host}]" if ":" in host else host
    server = ThreadingHTTPServer((host, port), None)
    base_url = f"http://{shown}:{server.server_address[1]}"
    server.RequestHandlerClass = make_handler(token, config_path, origins or [], base_url)
    server.base_url = base_url
    return server


def serve(host: str = "127.0.0.1", port: int = PORT, config_path: str | None = None,
          origins: list[str] | None = None) -> int:
    token, source = load_token(config_path)
    server = make_server(host, port, token, config_path, origins)
    print(f"when-free {__version__} on {server.base_url}\n"
          f"  OpenAPI:  {server.base_url}/openapi.json\n"
          f"  Token:    {'from ' + source if source == 'WHENFREE_TOKEN' else 'in ' + source}"
          f" (send it as: Authorization: Bearer <token>)\n"
          f"  Try:      curl -H \"Authorization: Bearer $(cat {token_path(config_path)})\" "
          f"'{server.base_url}/free_slots?days=tomorrow'\n"
          "Ctrl-C stops it.", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
