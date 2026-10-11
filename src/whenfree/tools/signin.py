"""How an account signs in. Scopes come from the registry, which is what knows each service."""
from __future__ import annotations

import getpass

from ..core.errors import Problem
from .connect import oauth

OAUTH = {
    "google": ("https://accounts.google.com/o/oauth2/v2/auth", "https://oauth2.googleapis.com/token"),
    "microsoft": (
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
    ),
}
HINTS = {
    "slack": "Slack bot token (xoxb-). Bot scopes: channels:read, channels:history, groups:read, groups:history, chat:write, users:read.",
    "github": "GitHub personal access token. Read repos and issues; contents are not required.",
    "notion": "Notion internal integration token.",
    "linear": "Linear personal API key.",
    "hubspot": "HubSpot private app token, with read on contacts and deals.",
}


def sign_in(account: str, scopes: tuple[str, ...], config_path: str | None) -> str:
    if account in OAUTH:
        if account == "microsoft":
            print("Teams channel history and posting may need an admin to approve the app.", flush=True)
        auth, token = OAUTH[account]
        return oauth.login(account, config_path, auth_url=auth, token_url=token, scopes=scopes)
    hint = HINTS.get(account)
    if hint is None:
        raise Problem(f"unknown service {account!r}")
    secret = getpass.getpass(f"{hint}\nPaste the token (it is not shown): ")
    if not secret.strip():
        raise Problem("no token was given")
    return oauth.save_token(account, config_path, secret)
