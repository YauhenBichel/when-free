"""Sign a service in so its tools can run. The MCP server does not collect passwords."""
from __future__ import annotations

import getpass

from ..connect import oauth
from ..core.errors import Problem
from ..drive.api import SCOPES as DRIVE_SCOPES
from ..gmail.api import SCOPES as GMAIL_SCOPES
from ..outlook.api import SCOPES as OUTLOOK_SCOPES
from ..teams.api import SCOPES as TEAMS_SCOPES

_GOOGLE = tuple(dict.fromkeys((*GMAIL_SCOPES, *DRIVE_SCOPES)))
_MICROSOFT = tuple(dict.fromkeys((*OUTLOOK_SCOPES, *TEAMS_SCOPES)))

OAUTH = {
    "google": ("https://accounts.google.com/o/oauth2/v2/auth", "https://oauth2.googleapis.com/token", _GOOGLE),
    "microsoft": (
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        _MICROSOFT,
    ),
}
TOKENS = ("slack", "github", "notion", "linear", "hubspot")
_HINTS = {
    "slack": "Slack bot token (xoxb-). Bot scopes: channels:read, channels:history, groups:read, groups:history, chat:write, users:read.",
    "github": "GitHub personal access token. Read repos and issues; contents are not required.",
    "notion": "Notion internal integration token.",
    "linear": "Linear personal API key.",
    "hubspot": "HubSpot private app token, with read on contacts and deals.",
}


def cmd_connect(args) -> int:
    service = args.service
    if service is None:
        from ..tools.registry import call
        text, _ = call("connected_accounts", {}, config_path=args.config)
        print(text)
        return 0
    if service in OAUTH:
        if service == "microsoft":
            print("Teams channel history and posting may need an admin to approve the app.", flush=True)
        auth, token, scopes = OAUTH[service]
        print(oauth.login(service, args.config, auth_url=auth, token_url=token, scopes=scopes))
        return 0
    secret = getpass.getpass(f"{_HINTS[service]}\nPaste the token (it is not shown): ")
    if not secret.strip():
        raise Problem("no token was given")
    print(oauth.save_token(service, args.config, secret))
    return 0
