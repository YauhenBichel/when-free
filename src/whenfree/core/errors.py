"""The one error a caller is expected to handle."""


class Problem(Exception):
    """Something the caller can fix. Its text is safe to show: it never contains a calendar address."""


def clip(value, limit: int = 80) -> str:
    """What the caller sent, quoted, and cut short: an error is not the place to hand megabytes back."""
    text = repr(value)
    return text if len(text) <= limit + 2 else f"{text[:limit]}… ({len(text)} characters)"
