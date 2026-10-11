"""The seams: calendars from any reader, one wording for every front end, tools added in one place."""
import pathlib

import pytest

from whenfree import api
from whenfree import tools
from whenfree.core import render

SAMPLE = (pathlib.Path(__file__).parent / "data" / "sample.ics").read_text()


@pytest.fixture(autouse=True)
def fixed_world(tmp_path, monkeypatch):
    monkeypatch.setenv("WHENFREE_CONFIG", str(tmp_path / "none.toml"))
    monkeypatch.setenv("WHENFREE_NOW", "2026-10-01T08:00:00")
    monkeypatch.setenv("WHENFREE_TZ", "Europe/London")
    monkeypatch.delenv("WHENFREE_CALENDARS", raising=False)


def test_calendars_can_come_from_any_reader():
    asked = []
    reader = lambda source: asked.append(source) or SAMPLE
    result = api.find_free(api.Query(days="2026-10-07", hours="10:00-16:00", calendars=["memory:work"]), reader=reader)
    assert asked == ["memory:work"]
    assert result["days"][0]["free"] == [["10:15", "12:00"], ["13:00", "16:00"]]
    assert api.check_calendars(calendars=["memory:work"], reader=reader)["calendars"][0]["events"] == 13


def test_a_reader_that_fails_names_the_calendar_not_the_address():
    def reader(source):
        raise OSError("refused")
    with pytest.raises(api.Problem) as e:
        api.find_free(api.Query(days="2026-10-07", calendars=["https://example.com/SECRET.ics"]), reader=reader)
    assert "calendar 1" in str(e.value) and "SECRET" not in str(e.value)


def test_every_front_end_words_the_answer_the_same_way():
    result = api.find_free(api.Query(message="Wednesday 30th or Friday 2nd, 10am-4pm", calendars=["x"]),
                           reader=lambda s: SAMPLE)
    text = render.answer(result)
    assert text.startswith(render.header(result))
    assert "- Fri 2 Oct: 10:15–13:45" in text and "already past: 2026-09-30" in text
    assert "already past: Wed 30 Sep" in "\n".join(render.notes(result, past_as_labels=True))


def test_a_tool_is_one_registry_entry(monkeypatch):
    spec = {"name": "echo", "description": "Echo.", "inputSchema": {"type": "object", "properties": {
        "n": {"type": "integer"}, "loud": {"type": "boolean"}}, "additionalProperties": False}}
    monkeypatch.setitem(tools.REGISTRY, "echo", tools.Tool(spec, lambda args, cfg: (str(args), args)))
    assert tools.call("echo", {"n": 2}) == ("{'n': 2}", {"n": 2})
    with pytest.raises(api.Problem):
        tools.call("echo", {"n": "2"})


def test_query_strings_are_converted_by_the_schema():
    tool = tools.get("free_slots")
    assert tool.coerce([("min_minutes", "30"), ("weekends", "true"), ("include_busy", ""), ("days", "tomorrow")]) == \
        {"min_minutes": 30, "weekends": True, "include_busy": True, "days": "tomorrow"}
    assert tool.coerce([("min_minutes", "lots")]) == {"min_minutes": "lots"}       # left for validate to explain


def test_the_demo_needs_no_calendar_and_no_settings(capsys, monkeypatch):
    from whenfree import cli
    monkeypatch.setenv("WHENFREE_CALENDARS", "/no/such/calendar.ics")      # ignored: the demo brings its own
    assert cli.main(["demo", "--tz", "Europe/London"]) == 0
    out = capsys.readouterr().out
    assert "Lunch with Sam" in out and "whenfree add" in out
    days = [line for line in out.splitlines() if line.startswith("  - ")]
    assert [d.split(":")[0].split()[1] for d in days] == ["Tue", "Wed", "Thu"]


# Which components each one may import. The domain depends on nothing. A service may use connect and core.
# Only tools/__init__.py may import a service. The MCP server imports tools, not the services.
SERVICES = {"gmail", "drive", "outlook", "teams", "slack", "github", "notion", "linear", "hubspot"}
ALLOWED = {
    "core": set(),
    "messages": {"core"},
    "settings": set(),
    "calendars": {"core", "settings"},
    "api": {"core", "messages", "calendars", "settings"},
    "connect": {"core", "settings"},
    "gmail": {"connect", "core"},
    "drive": {"connect", "core"},
    "outlook": {"connect", "core"},
    "teams": {"connect", "core"},
    "slack": {"connect", "core"},
    "github": {"connect", "core"},
    "notion": {"connect", "core"},
    "linear": {"connect", "core"},
    "hubspot": {"connect", "core"},
    "tools": {"api", "core", "connect"} | SERVICES,
    "mcp": {"core", "tools"},
    "devices": {"api", "core", "settings"},
    "smarthome": {"api", "core"},
    "web": {"api", "tools", "devices", "calendars", "core", "settings"},
    "cli": {"api", "mcp", "tools", "web", "devices", "smarthome", "core", "messages", "calendars", "settings"},
}


def _component(path):
    parts = path.relative_to(PACKAGE).parts
    if parts[0] == "tools" and len(parts) > 2 and parts[1] in SERVICES | {"connect"}:
        return parts[1]
    if len(parts) == 1:
        name = parts[0].removesuffix(".py")
        return name if name in {"api", "mcp"} else None
    return parts[0].removesuffix(".py")


def _label(parts):
    if not parts:
        return None
    if parts[0] == "tools" and len(parts) > 1 and parts[1] in SERVICES | {"connect"}:
        return parts[1]
    return parts[0].removesuffix(".py")


def _imported_components(path):
    import ast
    tree = ast.parse(path.read_text())
    here = list(path.relative_to(PACKAGE).parts[:-1])
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            up = node.level - 1
            base = here[: len(here) - up] if up <= len(here) else []
            if node.module:
                found.add(_label(base + node.module.split(".")))
            else:
                found.update(_label(base + [alias.name]) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("whenfree."):
            found.add(_label(node.module.split(".")[1:]))
    return {name for name in found if name} & set(ALLOWED)


PACKAGE = pathlib.Path(__file__).parent.parent / "src" / "whenfree"


@pytest.mark.parametrize("path", sorted(PACKAGE.rglob("*.py")), ids=lambda p: str(p.relative_to(PACKAGE)))
def test_components_depend_only_on_what_they_may(path):
    me = _component(path)
    if me is None:
        return                                     # __init__.py, __main__.py at the top
    imported = _imported_components(path)
    assert imported - ALLOWED[me] - {me} == set()
    # The registry is the one file that may name a service. Calendar code and sign-in may not.
    if me == "tools" and path.name != "__init__.py":
        assert not imported & SERVICES
