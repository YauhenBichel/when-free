"""GitHub, as tools. Reading repos and issues, and commenting when the user asked to comment. No pushes."""
from __future__ import annotations

import urllib.parse

from ..connect import http, schema, session, text
from ..core.errors import Problem

ACCOUNT = "github"
SCOPES = ()
_BASE = "https://api.github.com"
_NAME = r"^[A-Za-z0-9_.-]+$"


def _headers(config_path: str | None) -> dict:
    return session.bearer(ACCOUNT, config_path, {
        "accept": "application/vnd.github+json",
        "x-github-api-version": "2022-11-28",
        "user-agent": "when-free",
    })


def _get(url: str, config_path: str | None):
    return http.json_request("GET", url, _headers(config_path), account=ACCOUNT)


def _repo(arguments: dict) -> str:
    import re
    owner, repo = arguments.get("owner"), arguments.get("repo")
    if not all(isinstance(part, str) and re.fullmatch(_NAME, part) for part in (owner, repo)):
        raise Problem("owner and repo should be the names github_repos returned")
    return f"{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}"


def repos(arguments: dict, config_path: str | None):
    # The list endpoint returns a JSON array, which the object helper refuses.
    return _repos_raw(config_path, text.limit(arguments.get("max")))


def _repos_raw(config_path: str | None, n: int):
    import json
    status, raw = http.request("GET", f"{_BASE}/user/repos?per_page={n}&sort=updated", _headers(config_path))
    if status == 401:
        raise Problem(f"{ACCOUNT} is not connected, or the login expired. Run: whenfree connect {ACCOUNT}")
    if status >= 400:
        raise Problem(f"the service refused the request ({status})")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = []
    rows = [{"name": item.get("full_name"), "private": bool(item.get("private"))} for item in (data or [])[:n] if isinstance(item, dict)]
    return ("\n".join(row["name"] or "" for row in rows) or "no repositories", {"repos": rows})


def issues(arguments: dict, config_path: str | None):
    import json
    n = text.limit(arguments.get("max"))
    status, raw = http.request("GET", f"{_BASE}/repos/{_repo(arguments)}/issues?state=open&per_page={n}", _headers(config_path))
    if status >= 400:
        raise Problem(f"the service refused the request ({status})")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = []
    if not isinstance(data, list):
        raise Problem(f"the service refused the request ({status})")
    rows = [{"number": item.get("number"), "title": item.get("title")} for item in data[:n] if isinstance(item, dict) and "pull_request" not in item]
    return ("\n".join(f"#{row['number']}  {row['title']}" for row in rows) or "no open issues", {"issues": rows})


def issue(arguments: dict, config_path: str | None):
    number = arguments.get("number")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise Problem("number should be the issue number")
    got = _get(f"{_BASE}/repos/{_repo(arguments)}/issues/{number}", config_path)
    row = {"number": got.get("number"), "title": got.get("title"), "body": text.clip(got.get("body") or "")}
    return f"#{row['number']} {row['title']}\n\n{row['body']}", {"issue": row}


def comment(arguments: dict, config_path: str | None):
    number = arguments.get("number")
    body = arguments.get("body")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise Problem("number should be the issue number")
    if not isinstance(body, str) or not body.strip():
        raise Problem("github_comment needs the comment text. This posts the comment.")
    saved = http.json_request(
        "POST", f"{_BASE}/repos/{_repo(arguments)}/issues/{number}/comments",
        _headers(config_path), {"body": body}, account=ACCOUNT,
    )
    return "comment posted", {"id": saved.get("id"), "sent": True}


TOOLS = [
    (schema.tool("github_repos", "List the user's GitHub repositories. Does not push or change them.", {"max": schema.integer("How many to return. Default 8, at most 20.")}), repos),
    (schema.tool("github_issues", "List open issues on one repository. Pull requests are left out.", {"owner": schema.string("The owner."), "repo": schema.string("The repository."), "max": schema.integer("How many to return. Default 8, at most 20.")}), issues),
    (schema.tool("github_issue", "Read one GitHub issue.", {"owner": schema.string("The owner."), "repo": schema.string("The repository."), "number": schema.integer("The issue number.")}), issue),
    (schema.tool("github_comment", "Post a comment on a GitHub issue. This sends the comment. It does not push code.", {"owner": schema.string("The owner."), "repo": schema.string("The repository."), "number": schema.integer("The issue number."), "body": schema.string("The comment.")}), comment),
]
