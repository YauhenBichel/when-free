"""A small HTTP server for tools and devices that cannot start a command: Open WebUI, n8n, Shortcuts, phones.

    whenfree serve                     # http://127.0.0.1:8765, this computer only
    whenfree serve --lan               # also reachable from phones and tablets on your network

The tools (one path each, JSON in and out, described at /openapi.json), a page for phones at /m, your free slots
as a calendar feed at /free.ics, and the status right now at /status. Standard library only.

Who may ask:
- the owner's token (kept next to the settings file, or WHENFREE_TOKEN) may use every tool;
- a paired device's token (`whenfree devices add`) may see free time and the status, never event titles.

It listens on 127.0.0.1 unless told otherwise. There, a request whose Host is not this machine is refused, which
stops a web page from reaching it through a name that points here (DNS rebinding). Listening on another address
(`--lan`, `--host`) is a choice to be reachable by other names, so the Host check is then left out and the tokens
are what protect it; add `--tls-cert` and `--tls-key`, or put it behind Tailscale, to encrypt the traffic.
"""
from __future__ import annotations

import datetime as dt
import hmac
import importlib.resources
import json
import os
import pathlib
import secrets
import socket
import ssl
import sys
import urllib.parse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .. import __version__, api, settings
from ..agents import tools
from ..calendars import cache
from ..devices import feed, pairing

PORT = 8765
MAX_BODY = 64 * 1024
LOCAL_NAMES = {"127.0.0.1", "localhost", "::1", "[::1]"}
CACHE_SECONDS = 300
FEED_DAYS = 14

STATIC = {                                            # the phone page: no data in it, so no token needed
    "m": ("index.html", "text/html; charset=utf-8"),
    "app.js": ("app.js", "text/javascript; charset=utf-8"),
    "app.css": ("app.css", "text/css; charset=utf-8"),
    "manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "icon.svg": ("icon.svg", "image/svg+xml"),
}
PAGE_HEADERS = {
    "Content-Security-Policy": ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
                                "connect-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'self'; "
                                "frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def token_path(config_path: str | None = None) -> pathlib.Path:
    """The owner's token lives next to the settings file, readable only by you."""
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


def lan_address() -> str:
    """This computer's address on the local network, as phones would reach it. No packet is sent."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))                  # a documentation address: only picks the route
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


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
                "403": {"description": "A paired device asked for something only the owner may see"},
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


@dataclass(frozen=True)
class Caller:
    """Who is asking: the owner, or a paired device by name."""
    device: str | None = None

    @property
    def owner(self) -> bool:
        return self.device is None

    def may(self, tool: str, arguments: dict) -> bool:
        if self.owner:
            return True
        return tool in pairing.DEVICE_TOOLS and not arguments.get("include_busy")


def make_handler(token: str, config_path: str | None, origins: list[str], base_url: str, reader):
    loopback = urllib.parse.urlsplit(base_url).hostname in LOCAL_NAMES
    devices = pairing.Devices(pairing.store_path(config_path))
    assets = importlib.resources.files("whenfree.devices") / "mobile"

    class Handler(BaseHTTPRequestHandler):
        server_version = f"when-free/{__version__}"
        sys_version = ""

        def log_message(self, fmt, *args):            # one short line per request: never the query, body or token
            sys.stderr.write(f"{self.command} {urllib.parse.urlsplit(self.path).path} {args[1] if len(args) > 1 else ''}\n")

        # ---------- answering ----------

        def _raw(self, status: int, data: bytes, content_type: str | None, extra: dict | None = None) -> None:
            self.send_response(status)
            if content_type:
                self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            origin = self.headers.get("Origin")
            if origin and origin in origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _send(self, status: int, body: dict | None, extra: dict | None = None) -> None:
            data = b"" if body is None else json.dumps(body, ensure_ascii=False, indent=2).encode()
            self._raw(status, data, "application/json; charset=utf-8" if body is not None else None, extra)

        def _refuse(self) -> None:
            self._send(401, {"ok": False, "error": "send the token as: Authorization: Bearer <token>"},
                       {"WWW-Authenticate": "Bearer"})

        # ---------- who is asking ----------

        def _local_host(self) -> bool:
            if not loopback:
                return True
            host = (self.headers.get("Host") or "").strip().lower()       # "127.0.0.1:8765", "[::1]:8765"
            name = host[:host.find("]") + 1] if host.startswith("[") else host.split(":")[0]
            return name in LOCAL_NAMES or name == urllib.parse.urlsplit(base_url).hostname

        def _caller(self, query_token: str | None = None) -> Caller | None:
            got = self.headers.get("Authorization", "")
            given = got[7:].strip() if got.startswith("Bearer ") else (query_token or "")
            if not given:
                return None
            if hmac.compare_digest(given.encode(), token.encode()):
                return Caller()
            device = devices.find(given)
            return Caller(device.name) if device else None

        # ---------- routes ----------

        def _route(self, body: dict | None) -> None:
            if not self._local_host():
                return self._send(403, {"ok": False, "error": "this server answers only requests addressed to this machine"})
            url = urllib.parse.urlsplit(self.path)
            name = url.path.strip("/")
            query = urllib.parse.parse_qsl(url.query, keep_blank_values=True)
            if name in ("", "health"):
                return self._send(200, {"ok": True, "name": "when-free", "version": __version__,
                                        "openapi": f"{base_url}/openapi.json"})
            if name == "openapi.json":
                return self._send(200, openapi(base_url))
            if name in STATIC:
                file, kind = STATIC[name]
                return self._raw(200, (assets / file).read_bytes(), kind, PAGE_HEADERS)
            if name == "free.ics":
                return self._feed(dict(query).get("t"))
            if name == "status.txt":
                return self._status_text()
            tool = tools.REGISTRY.get(name)
            if tool is None:
                return self._send(404, {"ok": False, "error": f"no such path. Tools: {', '.join('/' + t for t in tools.REGISTRY)}"})
            caller = self._caller()
            if caller is None:
                return self._refuse()
            arguments = body if body is not None else tool.coerce(query)
            if not caller.may(name, arguments if isinstance(arguments, dict) else {}):
                return self._send(403, {"ok": False, "error": f"the device '{caller.device}' may see free time and "
                                                             "the status, not event titles or calendar details"})
            try:
                text, data = tools.call(name, arguments, config_path=config_path, reader=reader)
            except api.Problem as e:
                return self._send(400, {"ok": False, "error": str(e)})
            except Exception as e:                    # never a traceback, never an address
                return self._send(500, {"ok": False, "error": f"when-free failed: {e.__class__.__name__}"})
            self._send(200, {"ok": True, "text": text, "data": data})

        def _feed(self, query_token: str | None) -> None:
            """Calendar apps cannot send a header, so the token may come in the address: ?t=..."""
            if self._caller(query_token) is None:
                return self._raw(401, b"not paired\n", "text/plain; charset=utf-8")
            try:
                today = settings.now(dt.timezone.utc).date()
                result = api.find_free(api.Query(start=today.isoformat(),
                                                 end=(today + dt.timedelta(days=FEED_DAYS - 1)).isoformat(),
                                                 config_path=config_path), reader=reader)
            except api.Problem as e:
                # A feed that fails keeps the calendar app's last copy rather than showing an empty week as free.
                return self._raw(503, f"{e}\n".encode(), "text/plain; charset=utf-8", {"Retry-After": "900"})
            host = urllib.parse.urlsplit(base_url).hostname or "when-free"
            self._raw(200, feed.calendar(result, host=host).encode(), "text/calendar; charset=utf-8",
                      {"Content-Disposition": 'inline; filename="free.ics"'})

        def _status_text(self) -> None:
            """One line of plain text, for the smallest devices and scripts."""
            if self._caller() is None:
                return self._refuse()
            try:
                text, _ = tools.call("status", {}, config_path=config_path, reader=reader)
            except api.Problem as e:
                return self._raw(503, f"? {e}\n".encode(), "text/plain; charset=utf-8")
            self._raw(200, (text.splitlines()[0] + "\n").encode(), "text/plain; charset=utf-8")

        # ---------- methods ----------

        def do_GET(self):
            self._route(None)

        do_HEAD = do_GET

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
                origins: list[str] | None = None, *, tls: tuple[str, str] | None = None,
                reader=None, public_host: str | None = None) -> ThreadingHTTPServer:
    """`public_host` is the name or address devices use, when it differs from the one listened on (0.0.0.0)."""
    server = ThreadingHTTPServer((host, port), None)
    if tls:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(*tls)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    shown = public_host or host
    shown = f"[{shown}]" if ":" in shown else shown
    base_url = f"{'https' if tls else 'http'}://{shown}:{server.server_address[1]}"
    server.RequestHandlerClass = make_handler(token, config_path, origins or [], base_url,
                                              reader if reader is not None else cache.MemoryCache(CACHE_SECONDS))
    server.base_url = base_url
    return server


def serve(host: str = "127.0.0.1", port: int = PORT, config_path: str | None = None,
          origins: list[str] | None = None, *, lan: bool = False, tls: tuple[str, str] | None = None) -> int:
    token, source = load_token(config_path)
    if lan and host == "127.0.0.1":
        host = "0.0.0.0"
    public = lan_address() if host in ("0.0.0.0", "::") else None
    server = make_server(host, port, token, config_path, origins, tls=tls, public_host=public)
    lines = [f"when-free {__version__} on {server.base_url}",
             f"  OpenAPI:  {server.base_url}/openapi.json",
             f"  Token:    {'from ' + source if source == 'WHENFREE_TOKEN' else 'in ' + source}"
             " (send it as: Authorization: Bearer <token>)"]
    if public:
        lines += [f"  Phones:   whenfree devices add \"Your phone\" --url {server.base_url}",
                  "  Reachable from your network; the tokens protect it." +
                  ("" if tls else " Traffic is not encrypted: use it at home, or with --tls-cert/--tls-key or Tailscale.")]
    lines.append("Ctrl-C stops it.")
    print("\n".join(lines), file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
