"""The shape of one MCP tool, shared so every service describes its tools the same way."""
from __future__ import annotations


def string(description: str) -> dict:
    return {"type": "string", "description": description}


def integer(description: str, minimum: int = 1) -> dict:
    return {"type": "integer", "minimum": minimum, "description": description}


def tool(name: str, description: str, properties: dict, required: tuple[str, ...] = ()) -> dict:
    """`required` names the arguments the tool cannot work without, so a model sees them before it calls."""
    schema = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        assert set(required) <= set(properties), f"{name}: required names an unknown argument"
        schema["required"] = list(required)
    return {"name": name, "description": description, "inputSchema": schema}
