"""The one error a caller is expected to handle."""


class Problem(Exception):
    """Something the caller can fix. Its text is safe to show: it never contains a calendar address."""
