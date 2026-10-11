"""HubSpot, as tools. Reading contacts and deals. This module does not change them."""
from __future__ import annotations

from ..connect import http, schema, session, text
from ..core.errors import Problem

ACCOUNT = "hubspot"
SCOPES = ()
_BASE = "https://api.hubapi.com/crm/v3/objects"


def _rows(config_path: str | None, kind: str, properties: list[str], query: str | None, n: int) -> list[dict]:
    headers = session.bearer(ACCOUNT, config_path)
    if query:
        got = http.json_request(
            "POST", f"{_BASE}/{kind}/search", headers,
            {"query": query, "limit": n, "properties": properties}, account=ACCOUNT,
        )
    else:
        got = http.json_request(
            "GET", f"{_BASE}/{kind}?limit={n}&properties={','.join(properties)}", headers, account=ACCOUNT,
        )
    rows = []
    for item in (got.get("results") or [])[:n]:
        props = item.get("properties") or {}
        rows.append({"id": item.get("id"), **{key: props.get(key) or "" for key in properties}})
    return rows


def contacts(arguments: dict, config_path: str | None):
    query = arguments.get("query")
    if query is not None and not isinstance(query, str):
        raise Problem("query should be text")
    rows = _rows(config_path, "contacts", ["email", "firstname", "lastname"], query or None, text.limit(arguments.get("max")))
    lines = [f"{row.get('firstname', '')} {row.get('lastname', '')}  {row.get('email', '')}".strip() for row in rows]
    return ("\n".join(lines) or "no contacts", {"contacts": rows})


def deals(arguments: dict, config_path: str | None):
    query = arguments.get("query")
    if query is not None and not isinstance(query, str):
        raise Problem("query should be text")
    rows = _rows(config_path, "deals", ["dealname", "amount", "dealstage"], query or None, text.limit(arguments.get("max")))
    lines = [f"{row.get('dealname', '')}  {row.get('amount', '')}  {row.get('dealstage', '')}".strip() for row in rows]
    return ("\n".join(lines) or "no deals", {"deals": rows})


TOOLS = [
    (schema.tool("hubspot_contacts", "List or search HubSpot contacts. Read only.", {"query": schema.string("Optional words to search for."), "max": schema.integer("How many to return. Default 8, at most 20.")}), contacts),
    (schema.tool("hubspot_deals", "List or search HubSpot deals. Read only.", {"query": schema.string("Optional words to search for."), "max": schema.integer("How many to return. Default 8, at most 20.")}), deals),
]
