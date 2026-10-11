"""Notion, as tools. Search and read. This module does not change pages."""
from __future__ import annotations

import urllib.parse

from ..connect import http, schema, session, text
from ..core.errors import Problem

ACCOUNT = "notion"
SCOPES = ()
_BASE = "https://api.notion.com/v1"


def _headers(config_path: str | None) -> dict:
    return session.bearer(ACCOUNT, config_path, {"notion-version": "2022-06-28"})


def search(arguments: dict, config_path: str | None):
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        raise Problem("notion_search needs a query")
    n = text.limit(arguments.get("max"))
    got = http.json_request("POST", f"{_BASE}/search", _headers(config_path), {"query": query, "page_size": n}, account=ACCOUNT)
    rows = []
    for item in (got.get("results") or [])[:n]:
        title = ""
        props = item.get("properties") or {}
        for prop in props.values():
            rich = prop.get("title") if isinstance(prop, dict) else None
            if rich:
                title = "".join(part.get("plain_text") or "" for part in rich)
                break
        rows.append({"id": item.get("id"), "title": title or item.get("url") or ""})
    return ("\n".join(f"{row['title']}  [{row['id']}]" for row in rows) or "no pages", {"pages": rows})


def read(arguments: dict, config_path: str | None):
    block = arguments.get("id")
    if not isinstance(block, str) or not block.strip() or any(ch.isspace() or ch in "?#" for ch in block) or ".." in block:
        raise Problem("id should be the id notion_search returned")
    got = http.json_request(
        "GET", f"{_BASE}/blocks/{urllib.parse.quote(block, safe='')}/children?page_size=50",
        _headers(config_path), account=ACCOUNT,
    )
    lines = []
    for item in got.get("results") or []:
        kind = item.get("type") or ""
        rich = ((item.get(kind) or {}).get("rich_text")) or []
        line = "".join(part.get("plain_text") or "" for part in rich)
        if line:
            lines.append(line)
    body = text.clip("\n".join(lines))
    return body or "no text", {"text": body}


TOOLS = [
    (schema.tool("notion_search", "Search the user's Notion. Read only.", {"query": schema.string("Words to search for."), "max": schema.integer("How many to return. Default 8, at most 20.")}), search),
    (schema.tool("notion_read", "Read the text of one Notion page or block. Read only.", {"id": schema.string("The id notion_search returned.")}), read),
]
