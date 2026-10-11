"""The shape of one MCP tool, shared so every service describes its tools the same way."""
from __future__ import annotations


def string(description: str) -> dict:
    return {"type": "string", "description": description}


def integer(description: str, minimum: int = 1) -> dict:
    return {"type": "integer", "minimum": minimum, "description": description}


def tool(name: str, description: str, properties: dict) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": properties, "additionalProperties": False},
    }
