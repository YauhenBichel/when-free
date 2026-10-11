"""Google Drive, as tools. Read only. This module does not talk to Gmail."""
from __future__ import annotations

import urllib.parse

from ..connect import http, schema, session, text
from ..core.errors import Problem

ACCOUNT = "google"
SCOPES = ("https://www.googleapis.com/auth/drive.readonly",)
_BASE = "https://www.googleapis.com/drive/v3/files"


def _get(url: str, config_path: str | None) -> dict:
    return http.json_request("GET", url, session.bearer(ACCOUNT, config_path), account=ACCOUNT)


def search(arguments: dict, config_path: str | None):
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        raise Problem("drive_search needs a query, words from the file name")
    n = text.limit(arguments.get("max"))
    safe = query.replace("\\", "").replace("'", "")
    params = urllib.parse.urlencode({
        "q": f"name contains '{safe}' and trashed = false",
        "pageSize": n,
        "fields": "files(id,name,mimeType)",
    })
    got = _get(f"{_BASE}?{params}", config_path)
    files = [{"id": item.get("id"), "name": item.get("name"), "mimeType": item.get("mimeType")} for item in (got.get("files") or [])[:n]]
    lines = [f"{item['name']}  [{item['id']}]" for item in files]
    return ("\n".join(lines) or "no files", {"files": files})


def read(arguments: dict, config_path: str | None):
    fid = text.ident(arguments.get("id"), "file id")
    meta = _get(f"{_BASE}/{fid}?fields=id,name,mimeType", config_path)
    mime = meta.get("mimeType") or ""
    headers = session.bearer(ACCOUNT, config_path)
    if mime.startswith("application/vnd.google-apps."):
        export = "text/csv" if mime.endswith(".spreadsheet") else "text/plain"
        if mime.endswith((".document", ".spreadsheet", ".presentation")):
            status, raw = http.request("GET", f"{_BASE}/{fid}/export?mimeType={urllib.parse.quote(export)}", headers)
        else:
            return f"{meta.get('name')} is not a text file", {"file": meta}
    else:
        status, raw = http.request("GET", f"{_BASE}/{fid}?alt=media", headers)
    if status >= 400:
        raise Problem(f"the service refused the request ({status})")
    try:
        body = raw.decode("utf-8")
    except UnicodeDecodeError:
        return f"{meta.get('name')} is not a text file", {"file": meta}
    return text.clip(body), {"file": {**meta, "text": text.clip(body)}}


TOOLS = [
    (schema.tool("drive_search", "Search the user's Google Drive by file name. Read only.", {"query": schema.string("Words from the file name."), "max": schema.integer("How many to return. Default 8, at most 20.")}), search),
    (schema.tool("drive_read", "Read one Drive file as text, by the id drive_search returned. Read only.", {"id": schema.string("The file id.")}), read),
]
