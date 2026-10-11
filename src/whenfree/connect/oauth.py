"""Browser login for Google and Microsoft. The client secret stays in a local file and is never printed."""
from __future__ import annotations

import hashlib
import http.server as std_http
import json
import secrets
import threading
import time
import urllib.parse
import webbrowser

from ..core.errors import Problem
from . import http, store


def login(account: str, config_path: str | None, *, auth_url: str, token_url: str, scopes: tuple[str, ...]) -> str:
    client = _client(account, config_path)
    port, code = _listen()
    verifier = secrets.token_urlsafe(64)
    challenge = hashlib.sha256(verifier.encode()).digest()
    challenge = _b64(challenge)
    state = secrets.token_urlsafe(24)
    query = urllib.parse.urlencode({
        "client_id": client["client_id"],
        "redirect_uri": f"http://127.0.0.1:{port}/",
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    })
    webbrowser.open(f"{auth_url}?{query}")
    got = code.wait(180)
    if not got or got.get("state") != state or not got.get("code"):
        raise Problem(f"the {account} login did not finish. Try `whenfree connect {account}` again.")
    status, raw = http.request(
        "POST",
        token_url,
        body=urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": got["code"],
            "redirect_uri": f"http://127.0.0.1:{port}/",
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "code_verifier": verifier,
        }).encode(),
    )
    try:
        token = json.loads(raw)
    except json.JSONDecodeError:
        token = {}
    if status >= 400 or not isinstance(token, dict) or not token.get("access_token"):
        raise Problem(f"the {account} login was refused. Check the client file and try again.")
    store.write(f"{account}-token.json", config_path, {
        "access_token": token["access_token"],
        "refresh_token": token.get("refresh_token", ""),
        "expires_at": time.time() + int(token.get("expires_in") or 3600),
        "token_url": token_url,
        "client_id": client["client_id"],
    })
    return f"connected {account}. The login is saved on this computer only."


def save_token(account: str, config_path: str | None, token: str) -> str:
    store.write(f"{account}-token.json", config_path, {"access_token": token.strip()})
    return f"connected {account}. The token is saved on this computer only."


def _client(account: str, config_path: str | None) -> dict:
    file = store.path(f"{account}-client.json", config_path)
    data = store.read(f"{account}-client.json", config_path) or {}
    data = data.get("installed") or data.get("web") or data
    if not data.get("client_id") or not data.get("client_secret"):
        raise Problem(
            f"save a desktop OAuth client as {file} "
            f'(keys "client_id" and "client_secret", or Google\'s "installed" object). '
            "Do not paste the secret into chat."
        )
    return data


def _b64(raw: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _listen() -> tuple[int, "_Box"]:
    box: _Box = _Box()

    class Handler(std_http.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            box.put({key: values[0] for key, values in query.items() if values})
            self.send_response(200)
            self.send_header("content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"when-free is connected. You can close this tab.")

        def log_message(self, fmt: str, *args) -> None:
            return

    server = std_http.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()
    return server.server_address[1], box


class _Box:
    def __init__(self) -> None:
        self._event = threading.Event()
        self.value: dict | None = None

    def put(self, value: dict) -> None:
        self.value = value
        self._event.set()

    def wait(self, seconds: int) -> dict | None:
        self._event.wait(seconds)
        return self.value
