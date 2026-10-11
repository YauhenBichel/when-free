"""Outlook mail, as tools. Reading, and a draft that is not sent. This module does not talk to Teams."""
from __future__ import annotations

import urllib.parse

from ..connect import http, schema, session, text
from ...core.errors import Problem

ACCOUNT = "microsoft"
SCOPES = ("offline_access", "User.Read", "Mail.Read", "Mail.ReadWrite")
_BASE = "https://graph.microsoft.com/v1.0/me/messages"


def _get(url: str, config_path: str | None) -> dict:
    return http.json_request("GET", url, session.bearer(ACCOUNT, config_path), account=ACCOUNT)


def _row(item: dict, *, body: bool) -> dict:
    sender = ((item.get("from") or {}).get("emailAddress") or {}).get("address") or ""
    out = {
        "id": item.get("id"),
        "subject": item.get("subject") or "",
        "from": sender,
        "date": item.get("receivedDateTime") or "",
    }
    if body:
        content = ((item.get("body") or {}).get("content")) or ""
        out["body"] = text.clip(text.plain(content) if "<" in content else content)
    else:
        out["preview"] = text.clip(item.get("bodyPreview") or "", 500)
    return out


def search(arguments: dict, config_path: str | None):
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        raise Problem("outlook_search needs a query")
    n = text.limit(arguments.get("max"))
    quoted = urllib.parse.quote('"' + query.replace('"', "") + '"')
    got = _get(f"{_BASE}?$search={quoted}&$top={n}&$select=id,subject,from,receivedDateTime,bodyPreview", config_path)
    rows = [_row(item, body=False) for item in (got.get("value") or [])[:n]]
    lines = [f"{row['date']}  {row['from']}  {row['subject']}  [{row['id']}]" for row in rows]
    return ("\n".join(lines) or "no messages", {"messages": rows})


def read(arguments: dict, config_path: str | None):
    mid = text.path_id(arguments.get("id"), "id")
    item = _get(f"{_BASE}/{urllib.parse.quote(mid, safe='')}?$select=id,subject,from,receivedDateTime,body", config_path)
    row = _row(item, body=True)
    return f"From: {row['from']}\nSubject: {row['subject']}\n\n{row.get('body', '')}", {"message": row}


def draft(arguments: dict, config_path: str | None):
    to, subject, body = arguments.get("to"), arguments.get("subject"), arguments.get("body")
    if not all(isinstance(part, str) and part.strip() for part in (to, subject, body)):
        raise Problem("outlook_draft needs to, subject and body. It saves a draft and does not send it.")
    saved = http.json_request(
        "POST", _BASE, session.bearer(ACCOUNT, config_path),
        {"subject": subject, "body": {"contentType": "Text", "content": body},
         "toRecipients": [{"emailAddress": {"address": to}}]},
        account=ACCOUNT,
    )
    return f"draft saved ({saved.get('id', '')}). It was not sent.", {"id": saved.get("id"), "sent": False}


TOOLS = [
    (schema.tool("outlook_search", "Search the user's Outlook mail. Does not send mail.", {"query": schema.string("Words to search for."), "max": schema.integer("How many to return. Default 8, at most 20.")}), search),
    (schema.tool("outlook_read", "Read one Outlook message by the id outlook_search returned. Does not send mail.", {"id": schema.string("The message id.")}), read),
    (schema.tool("outlook_draft", "Save an Outlook draft. It does not send the message.", {"to": schema.string("Recipient address."), "subject": schema.string("Subject."), "body": schema.string("Plain text body.")}), draft),
]
