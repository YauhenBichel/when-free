"""A saved login, refreshed when it has expired. The access token is for the request header only."""
from __future__ import annotations

import json
import time
import urllib.parse

from ...core.errors import Problem
from . import http, store


def access_token(account: str, config_path: str | None) -> str:
    data = store.read(f"{account}-token.json", config_path)
    if not data or not data.get("access_token"):
        raise Problem(f"{account} is not connected. Run: whenfree connect {account}")
    expires = data.get("expires_at") or 0
    if expires and expires < time.time() + 60 and data.get("refresh_token"):
        data = _refresh(account, data, config_path)
    return str(data["access_token"])


def bearer(account: str, config_path: str | None, extra: dict | None = None) -> dict:
    headers = {"authorization": f"Bearer {access_token(account, config_path)}"}
    if extra:
        headers.update(extra)
    return headers


def _refresh(account: str, data: dict, config_path: str | None) -> dict:
    client = store.read(f"{account}-client.json", config_path) or {}
    client = client.get("installed") or client.get("web") or client
    secret = client.get("client_secret")
    client_id = data.get("client_id") or client.get("client_id")
    token_url = data.get("token_url")
    if not (secret and client_id and token_url):
        raise Problem(f"the {account} login expired. Run: whenfree connect {account}")
    status, raw = http.request(
        "POST",
        token_url,
        body=urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": data["refresh_token"],
            "client_id": client_id,
            "client_secret": secret,
        }).encode(),
    )
    try:
        token = json.loads(raw)
    except json.JSONDecodeError:
        token = {}
    if status >= 400 or not isinstance(token, dict) or not token.get("access_token"):
        raise Problem(f"the {account} login expired. Run: whenfree connect {account}")
    saved = {
        "access_token": token["access_token"],
        "refresh_token": token.get("refresh_token") or data["refresh_token"],
        "expires_at": time.time() + int(token.get("expires_in") or 3600),
        "token_url": token_url,
        "client_id": client_id,
    }
    store.write(f"{account}-token.json", config_path, saved)
    return saved
