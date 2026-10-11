"""Slack, as a bot. Reading channels, and posting when the user asked to post."""
from __future__ import annotations

import re
import urllib.parse

from ..connect import http, schema, session, text
from ...core.errors import Problem

ACCOUNT = "slack"
SCOPES = ()
_BASE = "https://slack.com/api"
_CODE = re.compile(r"^[a-z0-9_]+$")


def _call(method: str, url: str, config_path: str | None, body: dict | None = None) -> dict:
    data = http.json_request(method, url, session.bearer(ACCOUNT, config_path), body, account=ACCOUNT)
    if data.get("ok") is False:
        code = str(data.get("error") or "error")
        if not _CODE.fullmatch(code):
            code = "error"
        raise Problem(f"slack refused the request ({code})")
    return data


def channels(arguments: dict, config_path: str | None):
    got = _call("GET", f"{_BASE}/conversations.list?types=public_channel,private_channel&exclude_archived=true&limit=100", config_path)
    rows = [{"id": item.get("id"), "name": item.get("name")} for item in got.get("channels") or []]
    return ("\n".join(f"#{row['name']}  [{row['id']}]" for row in rows) or "no channels", {"channels": rows})


def history(arguments: dict, config_path: str | None):
    channel = text.ident(arguments.get("channel"), "channel")
    n = text.limit(arguments.get("max"))
    got = _call("GET", f"{_BASE}/conversations.history?{urllib.parse.urlencode({'channel': channel, 'limit': n})}", config_path)
    rows = [{"user": item.get("user") or "", "text": text.clip(item.get("text") or "", 1000), "ts": item.get("ts")} for item in (got.get("messages") or [])[:n]]
    return (text.clip("\n".join(f"{row['user']}: {row['text']}" for row in rows)) or "no messages", {"messages": rows})


def post(arguments: dict, config_path: str | None):
    channel = text.ident(arguments.get("channel"), "channel")
    body = arguments.get("text")
    if not isinstance(body, str) or not body.strip():
        raise Problem("slack_post needs the text to post")
    saved = _call("POST", f"{_BASE}/chat.postMessage", config_path, {"channel": channel, "text": body})
    return "posted to Slack", {"ts": saved.get("ts"), "sent": True}


TOOLS = [
    (schema.tool("slack_channels", "List Slack channels the bot can see.", {}), channels),
    (schema.tool("slack_history", "Read recent messages in a Slack channel.", {"channel": schema.string("The channel id from slack_channels."), "max": schema.integer("How many to return. Default 8, at most 20.")}), history),
    (schema.tool("slack_post", "Post a message to a Slack channel as the bot. This sends the message.", {"channel": schema.string("The channel id."), "text": schema.string("The message to post.")}), post),
]
