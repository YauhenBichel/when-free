"""Optional: ask a model you run yourself to read the proposed days and hours out of a message.

when-free never calls a hosted service on its own. This runs the command from the [extract] section of your
settings, and only if you configured one. The message is whatever you passed in, so point it at a local model
if the text is private.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess

PROMPT = """Extract the interview or meeting availability that this message asks for.
Today is {today} ({weekday}). Reply with JSON only, no other text:
{{"days": ["YYYY-MM-DD", ...], "hours": "HH:MM-HH:MM" or null, "minutes": integer or null}}
"days" are the dates offered or asked about. "hours" is the daily window if one is stated.
"minutes" is the length of the meeting if stated.

MESSAGE:
{message}"""


def run(command: list[str], message: str, today: dt.date, timeout: int = 120) -> dict | None:
    """{'days': [date, ...], 'hours': 'HH:MM-HH:MM' or None, 'minutes': int or None}, or None if it did not work."""
    prompt = PROMPT.format(today=today.isoformat(), weekday=today.strftime("%A"), message=message[:8000])
    try:
        if any("{prompt}" in part for part in command):
            argv, stdin = [part.replace("{prompt}", prompt) for part in command], None
        else:
            argv, stdin = command, prompt
        done = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    found = re.search(r"\{.*\}", done.stdout, re.S)
    if not found:
        return None
    try:
        data = json.loads(found.group(0))
        days = sorted({dt.date.fromisoformat(d) for d in data.get("days") or []})
    except (ValueError, TypeError, AttributeError):
        return None
    if not days:
        return None
    hours = data.get("hours") if isinstance(data.get("hours"), str) else None
    minutes = data.get("minutes") if isinstance(data.get("minutes"), int) and data["minutes"] > 0 else None
    return {"days": days, "hours": hours, "minutes": minutes}
