"""One HTTP call. Tests install a stand-in; the real call is urllib and is not used then."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable

from ...core.errors import Problem

_transport: Callable[[str, str, dict, bytes | None], tuple[int, bytes]] | None = None


def install(transport: Callable[[str, str, dict, bytes | None], tuple[int, bytes]] | None) -> None:
    """Replace the network. `None` puts the real call back."""
    global _transport
    _transport = transport


def request(method: str, url: str, headers: dict | None = None, body: dict | bytes | None = None, timeout: int = 30) -> tuple[int, bytes]:
    if isinstance(body, dict):
        raw: bytes | None = json.dumps(body).encode()
        content_type = "application/json"
    else:
        raw = body
        content_type = "application/x-www-form-urlencoded"
    hdrs = dict(headers or {})
    if raw is not None:
        hdrs.setdefault("content-type", content_type)
    if _transport is not None:
        return _transport(method, url, hdrs, raw)
    req = urllib.request.Request(url, data=raw, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (OSError, urllib.error.URLError) as exc:
        raise Problem(f"could not reach the service ({exc.__class__.__name__})") from None


def json_request(method: str, url: str, headers: dict | None = None, body: dict | None = None, *, account: str) -> dict | list:
    """A JSON object or array. The body of an error is never returned: it can echo a token."""
    status, raw = request(method, url, headers, body)
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        data = {}
    if status == 401:
        raise Problem(f"{account} is not connected, or the login expired. Run: whenfree connect {account}")
    if status >= 400 or not isinstance(data, (dict, list)):
        raise Problem(f"the service refused the request ({status})")
    return data
