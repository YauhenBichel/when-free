"""Gmail, as tools. Reading, and a draft that is not sent. This module does not talk to Drive."""
from __future__ import annotations

import base64
import urllib.parse

from ..connect import http, schema, session, text
from ..core.errors import Problem

ACCOUNT = "google"
SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
)
_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


def _get(url: str, config_path: str | None) -> dict:
    return http.json_request("GET", url, session.bearer(ACCOUNT, config_path), account=ACCOUNT)


def _decode(data: str) -> str:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad).decode("utf-8", "replace")


def _headers(payload: dict) -> dict:
    wanted = ("from", "to", "subject", "date")
    found = {}
    for item in payload.get("headers") or []:
        name = str(item.get("name") or "").lower()
        if name in wanted:
            found[name] = item.get("value") or ""
    return found


def _body(payload: dict) -> str:
    plain: list[str] = []
    html: list[str] = []

    def walk(part: dict) -> None:
        mime = part.get("mimeType") or ""
        data = (part.get("body") or {}).get("data")
        if data and mime.startswith("text/plain"):
            plain.append(_decode(data))
        elif data and mime.startswith("text/html"):
            html.append(text.plain(_decode(data)))
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    return text.clip("\n".join(plain or html))


def _message(item: dict, *, body: bool) -> dict:
    payload = item.get("payload") or {}
    out = {"id": item.get("id"), "threadId": item.get("threadId"), **_headers(payload)}
    if body:
        out["body"] = _body(payload)
    elif item.get("snippet"):
        out["snippet"] = text.clip(item["snippet"], 500)
    return out


def search(arguments: dict, config_path: str | None):
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        raise Problem("gmail_search needs a query, the same kind Gmail's search box takes")
    n = text.limit(arguments.get("max"))
    listed = _get(f"{_BASE}/messages?{urllib.parse.urlencode({'q': query, 'maxResults': n})}", config_path)
    messages = []
    for item in (listed.get("messages") or [])[:n]:
        mid = text.ident(item.get("id"), "message id")
        got = _get(f"{_BASE}/messages/{mid}?format=metadata&metadataHeaders=From&metadataHeaders=To&metadataHeaders=Subject&metadataHeaders=Date", config_path)
        got["snippet"] = item.get("snippet") or got.get("snippet")
        messages.append(_message(got, body=False))
    lines = [f"{m.get('date', '')}  {m.get('from', '')}  {m.get('subject', '')}  [{m.get('id')}]" for m in messages]
    return ("\n".join(lines) or "no messages", {"messages": messages})


def read(arguments: dict, config_path: str | None):
    mid = text.ident(arguments.get("id"), "message id")
    got = _get(f"{_BASE}/messages/{mid}?format=full", config_path)
    message = _message(got, body=True)
    head = f"From: {message.get('from', '')}\nSubject: {message.get('subject', '')}\nDate: {message.get('date', '')}\n"
    return head + "\n" + message.get("body", ""), {"message": message}


def thread(arguments: dict, config_path: str | None):
    tid = text.ident(arguments.get("id"), "thread id")
    got = _get(f"{_BASE}/threads/{tid}?format=full", config_path)
    messages = [_message(item, body=True) for item in got.get("messages") or []]
    lines = []
    for message in messages:
        lines.append(f"From: {message.get('from', '')}\nSubject: {message.get('subject', '')}\n{message.get('body', '')}")
    return text.clip("\n\n".join(lines)), {"messages": messages}


def labels(arguments: dict, config_path: str | None):
    got = _get(f"{_BASE}/labels", config_path)
    rows = [{"id": item.get("id"), "name": item.get("name")} for item in got.get("labels") or []]
    return "\n".join(row["name"] or "" for row in rows), {"labels": rows}


def draft(arguments: dict, config_path: str | None):
    to, subject, body = arguments.get("to"), arguments.get("subject"), arguments.get("body")
    if not all(isinstance(part, str) and part.strip() for part in (to, subject, body)):
        raise Problem("gmail_draft needs to, subject and body. It saves a draft and does not send it.")
    raw = base64.urlsafe_b64encode(
        f"To: {to}\r\nSubject: {subject}\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{body}".encode()
    ).decode()
    saved = http.json_request("POST", f"{_BASE}/drafts", session.bearer(ACCOUNT, config_path), {"message": {"raw": raw}}, account=ACCOUNT)
    draft_id = (saved.get("id") or "")
    return f"draft saved ({draft_id}). It was not sent.", {"id": draft_id, "sent": False}


TOOLS = [
    (schema.tool("gmail_search", "Search the user's Gmail. Returns ids, senders and subjects, not the full body. Use gmail_read for one message. Does not send mail.", {"query": schema.string("Gmail search, such as \"from:me@example.com newer_than:7d\"."), "max": schema.integer("How many to return. Default 8, at most 20.")}), search),
    (schema.tool("gmail_read", "Read one Gmail message by the id gmail_search returned. Does not send or change mail.", {"id": schema.string("The message id.")}), read),
    (schema.tool("gmail_thread", "Read one Gmail thread by id. Does not send or change mail.", {"id": schema.string("The thread id.")}), thread),
    (schema.tool("gmail_labels", "List Gmail labels. Does not change them.", {}), labels),
    (schema.tool("gmail_draft", "Save a Gmail draft. It does not send the message.", {"to": schema.string("Recipient address."), "subject": schema.string("Subject."), "body": schema.string("Plain text body.")}), draft),
]
