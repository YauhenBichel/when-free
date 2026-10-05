"""The status right now, in the shapes status bars and menu bars read.

    whenfree now --format waybar        Linux: Waybar custom module (JSON)
    whenfree now --format i3blocks      Linux: i3blocks, i3status-rust and similar (full, short, colour)
    whenfree now --format polybar       Linux: Polybar (colour tags)
    whenfree now --format xbar          macOS: SwiftBar and xbar; GNOME: Argos (menu lines)
    whenfree now --format tmux          a terminal status line
    whenfree now --format text | json   anything else, Windows included

A problem (a calendar that cannot be read) is shown as a state of its own, never as "free".
"""
from __future__ import annotations

import json

from ..core import render

FORMATS = ("text", "json", "waybar", "i3blocks", "polybar", "xbar", "tmux")
COLOURS = {"busy": "#e06c75", "free": "#98c379", "off": "#abb2bf", "error": "#e5c07b"}
DOTS = {"busy": "🔴", "free": "🟢", "off": "⚪", "error": "⚠️"}


def state(st: dict) -> str:
    if not st["free_now"]:
        return "busy"
    return "free" if st["in_hours"] else "off"


def short(st: dict) -> str:
    """As few characters as possible: "busy → 15:30", "free → 14:00", "free"."""
    if not st["free_now"]:
        return f"busy → {st['busy_until'][11:16]}"
    return f"free → {st['free_until'][11:16]}" if st["free_until"] else "free"


def show(st: dict, fmt: str) -> str:
    kind = state(st)
    line, details = render.status_line(st), render.status_details(st)
    if fmt == "json":
        return json.dumps(st, ensure_ascii=False)
    if fmt == "waybar":
        return json.dumps({"text": short(st), "alt": kind, "class": kind, "tooltip": "\n".join([line, *details])},
                          ensure_ascii=False)
    if fmt == "i3blocks":
        return "\n".join([line, short(st), COLOURS[kind]])
    if fmt == "polybar":
        return f"%{{F{COLOURS[kind]}}}{short(st)}%{{F-}}"
    if fmt == "xbar":
        return "\n".join([f"{DOTS[kind]} {short(st)}", "---", line, *details, "---", "Refresh | refresh=true"])
    if fmt == "tmux":
        return f"#[fg={COLOURS[kind]}]{short(st)}#[default]"
    return line


def show_problem(message: str, fmt: str) -> str:
    """What to show when the status cannot be known. Never "free"."""
    if fmt == "json":
        return json.dumps({"error": message}, ensure_ascii=False)
    if fmt == "waybar":
        return json.dumps({"text": "?", "alt": "error", "class": "error", "tooltip": message}, ensure_ascii=False)
    if fmt == "i3blocks":
        return "\n".join([f"when-free: {message}", "?", COLOURS["error"]])
    if fmt == "polybar":
        return f"%{{F{COLOURS['error']}}}?%{{F-}}"
    if fmt == "xbar":
        return "\n".join([f"{DOTS['error']} ?", "---", message])
    if fmt == "tmux":
        return "#[fg=yellow]?#[default]"
    return f"when-free: {message}"
