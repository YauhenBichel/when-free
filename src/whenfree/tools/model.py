"""One tool: its description for a model, and the function that runs it."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..core.errors import Problem

_TYPES = {"string": str, "integer": int, "boolean": bool}


@dataclass(frozen=True)
class Context:
    """What the MCP server passes to every tool: which settings file, and how to read calendars."""
    config_path: str | None = None
    reader: Callable[[str], str] | None = None


@dataclass(frozen=True)
class Tool:
    spec: dict
    run: Callable[[dict, Context], tuple[str, dict]]

    @property
    def name(self) -> str:
        return self.spec["name"]

    @property
    def properties(self) -> dict:
        return self.spec["inputSchema"]["properties"]

    def validate(self, arguments: dict) -> None:
        if not isinstance(arguments, dict):
            raise Problem("arguments must be an object")
        for key, value in arguments.items():
            if key not in self.properties:
                raise Problem(f"unknown argument {key!r} for {self.name}. Known: {', '.join(self.properties) or 'none'}")
            kind = _TYPES[self.properties[key]["type"]]
            if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
                raise Problem(f"argument {key!r} should be {self.properties[key]['type']}")

    def coerce(self, pairs: list[tuple[str, str]]) -> dict:
        """Arguments that arrived as text, converted by the schema. Bad values stay text so validate can explain them."""
        out: dict = {}
        for key, value in pairs:
            kind = self.properties.get(key, {}).get("type")
            if kind == "integer":
                try:
                    out[key] = int(value)
                    continue
                except ValueError:
                    pass
            elif kind == "boolean":
                out[key] = value.lower() in ("1", "true", "yes", "on", "")
                continue
            out[key] = value
        return out
