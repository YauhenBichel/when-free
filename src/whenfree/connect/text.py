"""Short, plain text for a model. Bodies from mail and chat are cut so one message cannot fill the reply."""
from __future__ import annotations

import re

from ..core.errors import Problem

_SCRIPT = re.compile(r"(?is)<(script|style)\b.*?>.*?</\1>")
_TAG = re.compile(r"(?s)<[^>]+>")
_SPACE = re.compile(r"\s+")
_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def plain(value: str) -> str:
    text = _TAG.sub(" ", _SCRIPT.sub(" ", value or ""))
    return _SPACE.sub(" ", text).strip()


def clip(value: str, limit: int = 6000) -> str:
    text = value or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…truncated"


def ident(value, label: str = "id") -> str:
    """An id a tool will put in a URL path. Anything else is refused before a request is made."""
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise Problem(f"{label} should be the id a search tool returned")
    return value


def limit(value, default: int = 8, cap: int = 20) -> int:
    try:
        n = int(default if value is None else value)
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, cap))
