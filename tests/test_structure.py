"""The seams: calendars from any reader, one wording for every front end, tools added in one place."""
import pathlib

import pytest

from whenfree import api, render, tools

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
