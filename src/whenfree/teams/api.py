"""Microsoft Teams, as tools. Reading, and posting a channel message when the user asked to post. This module does not talk to Outlook."""
from __future__ import annotations

import urllib.parse

from ..connect import http, schema, session, text
from ..core.errors import Problem

ACCOUNT = "microsoft"
SCOPES = (
    "offline_access", "User.Read",
    "Team.ReadBasic.All", "Channel.ReadBasic.All",
    "ChannelMessage.Read.All", "ChannelMessage.Send",
)
_BASE = "https://graph.microsoft.com/v1.0"


def _get(url: str, config_path: str | None) -> dict:
    return http.json_request("GET", url, session.bearer(ACCOUNT, config_path), account=ACCOUNT)


def _path_id(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(ch.isspace() or ch in "?#" for ch in value) or ".." in value:
        raise Problem(f"{label} should be an id a Teams tool returned")
    return urllib.parse.quote(value, safe="")


def joined(arguments: dict, config_path: str | None):
    got = _get(f"{_BASE}/me/joinedTeams", config_path)
    teams = [{"id": item.get("id"), "name": item.get("displayName")} for item in got.get("value") or []]
    return ("\n".join(f"{t['name']}  [{t['id']}]" for t in teams) or "no teams", {"teams": teams})


def channels(arguments: dict, config_path: str | None):
    team = _path_id(arguments.get("team"), "team")
    got = _get(f"{_BASE}/teams/{team}/channels", config_path)
    rows = [{"id": item.get("id"), "name": item.get("displayName")} for item in got.get("value") or []]
    return ("\n".join(f"{row['name']}  [{row['id']}]" for row in rows) or "no channels", {"channels": rows})


def history(arguments: dict, config_path: str | None):
    team, channel = _path_id(arguments.get("team"), "team"), _path_id(arguments.get("channel"), "channel")
    n = text.limit(arguments.get("max"))
    got = _get(f"{_BASE}/teams/{team}/channels/{channel}/messages?$top={n}", config_path)
    rows = []
    for item in (got.get("value") or [])[:n]:
        content = ((item.get("body") or {}).get("content")) or ""
        rows.append({
            "id": item.get("id"),
            "from": ((item.get("from") or {}).get("user") or {}).get("displayName") or "",
            "date": item.get("createdDateTime") or "",
            "text": text.clip(text.plain(content) if "<" in content else content, 1000),
        })
    lines = [f"{row['date']}  {row['from']}: {row['text']}" for row in rows]
    return (text.clip("\n".join(lines)) or "no messages", {"messages": rows})


def post(arguments: dict, config_path: str | None):
    team, channel = _path_id(arguments.get("team"), "team"), _path_id(arguments.get("channel"), "channel")
    body = arguments.get("text")
    if not isinstance(body, str) or not body.strip():
        raise Problem("teams_post needs the text to post")
    saved = http.json_request(
        "POST", f"{_BASE}/teams/{team}/channels/{channel}/messages",
        session.bearer(ACCOUNT, config_path),
        {"body": {"contentType": "text", "content": body}},
        account=ACCOUNT,
    )
    return "posted to Teams", {"id": saved.get("id"), "sent": True}


TOOLS = [
    (schema.tool("teams_joined", "List the Teams the user has joined.", {}), joined),
    (schema.tool("teams_channels", "List channels in one Team.", {"team": schema.string("The team id from teams_joined.")}), channels),
    (schema.tool("teams_history", "Read recent messages in a Teams channel.", {"team": schema.string("The team id."), "channel": schema.string("The channel id."), "max": schema.integer("How many to return. Default 8, at most 20.")}), history),
    (schema.tool("teams_post", "Post a message to a Teams channel. This sends the message.", {"team": schema.string("The team id."), "channel": schema.string("The channel id."), "text": schema.string("The message to post.")}), post),
]
