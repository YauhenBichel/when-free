"""Linear, as tools. Reading issues. This module does not change them."""
from __future__ import annotations

from ..connect import http, schema, session, text
from ...core.errors import Problem

ACCOUNT = "linear"
SCOPES = ()
_URL = "https://api.linear.app/graphql"


def _query(config_path: str | None, query: str, variables: dict) -> dict:
    got = http.json_request("POST", _URL, session.bearer(ACCOUNT, config_path), {"query": query, "variables": variables}, account=ACCOUNT)
    if got.get("errors"):
        raise Problem("the service refused the request")
    return got.get("data") or {}


def issues(arguments: dict, config_path: str | None):
    n = text.limit(arguments.get("max"))
    data = _query(
        config_path,
        "query($n: Int) { issues(first: $n) { nodes { identifier title url state { name } } } }",
        {"n": n},
    )
    rows = []
    for item in ((data.get("issues") or {}).get("nodes") or [])[:n]:
        rows.append({"id": item.get("identifier"), "title": item.get("title"), "state": (item.get("state") or {}).get("name"), "url": item.get("url")})
    return ("\n".join(f"{row['id']}  {row['title']}  {row['state'] or ''}" for row in rows) or "no issues", {"issues": rows})


def issue(arguments: dict, config_path: str | None):
    key = arguments.get("id")
    if not isinstance(key, str) or not key.strip():
        raise Problem("id should be the issue identifier, such as ENG-1")
    data = _query(
        config_path,
        "query($id: String!) { issue(id: $id) { identifier title description url } }",
        {"id": key},
    )
    item = data.get("issue") or {}
    if not item:
        raise Problem("no such issue")
    body = text.clip(item.get("description") or "")
    return f"{item.get('identifier')} {item.get('title')}\n\n{body}", {"issue": {"id": item.get("identifier"), "title": item.get("title"), "body": body, "url": item.get("url")}}


TOOLS = [
    (schema.tool("linear_issues", "List recent Linear issues. Read only.", {"max": schema.integer("How many to return. Default 8, at most 20.")}), issues),
    (schema.tool("linear_issue", "Read one Linear issue. Read only.", {"id": schema.string("The issue identifier, such as ENG-1.")}), issue),
]
