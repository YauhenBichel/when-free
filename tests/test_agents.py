"""The three ways an agent reaches when-free: the Python function, `whenfree call`, and the MCP server."""
import io
import json
import pathlib

import pytest

from whenfree import api, cli
from whenfree.agents import mcp, tools

SAMPLE = str(pathlib.Path(__file__).parent / "data" / "sample.ics")


@pytest.fixture(autouse=True)
def fixed_world(tmp_path, monkeypatch):
    settings = tmp_path / "config.toml"
    settings.write_text(f'hours = "10:00-16:00"\nme = ["me@example.com"]\n[[calendar]]\nname = "personal"\npath = "{SAMPLE}"\n')
    monkeypatch.setenv("WHENFREE_CONFIG", str(settings))
    monkeypatch.setenv("WHENFREE_NOW", "2026-10-01T08:00:00")
    monkeypatch.setenv("WHENFREE_TZ", "Europe/London")
    monkeypatch.delenv("WHENFREE_CALENDARS", raising=False)


# ---------- the Python function ----------

def test_find_free_returns_plain_data():
    result = api.find_free(api.Query(days="2026-10-07"))
    assert json.loads(json.dumps(result)) == result                 # nothing but dicts, lists, strings and numbers
    assert result["days"][0]["free"] == [["10:15", "12:00"], ["13:00", "16:00"]]
    assert result["days"][0]["label"] == "Wed 7 Oct" and result["timezone"] == "Europe/London"


def test_find_free_raises_a_problem_the_caller_can_show():
    with pytest.raises(api.Problem) as e:
        api.find_free(api.Query(days="2026-10-07", calendars=["/no/such/SECRET-TOKEN.ics"]))
    assert "SECRET-TOKEN" not in str(e.value)


# ---------- the tools ----------

def test_titles_are_left_out_unless_asked_for():
    text, data = tools.call("free_slots", {"days": "2026-10-01"})
    assert "Dentist" not in text and "busy" not in data["days"][0]
    assert "- Thu 1 Oct: 12:15–16:00" in text
    text, data = tools.call("free_slots", {"days": "2026-10-01", "include_busy": True})
    assert "Dentist" in text and data["days"][0]["busy"][0]["title"] == "Dentist"


def test_a_message_is_read_and_past_days_are_named():
    text, data = tools.call("free_slots", {"message": "Wednesday 30th or Friday 2nd, between 10:00am and 4:00pm", "min_minutes": 30})
    assert [d["date"] for d in data["days"]] == ["2026-10-02"] and data["past"] == ["2026-09-30"]
    assert "already past: 2026-09-30" in text and "pattern matching" in text


@pytest.mark.parametrize("name, arguments, said", [
    ("free_slots", {"day": "2026-10-07"}, "unknown argument"),
    ("free_slots", {"min_minutes": "60"}, "should be integer"),
    ("free_slots", {"weekends": 1}, "should be boolean"),
    ("free_slots", {"hours": "whenever"}, "cannot read hours"),
    ("book_meeting", {}, "unknown tool"),
])
def test_bad_calls_are_explained(name, arguments, said):
    with pytest.raises(api.Problem) as e:
        tools.call(name, arguments)
    assert said in str(e.value)


def test_check_calendars_gives_counts_and_no_details():
    text, data = tools.call("check_calendars")
    # 5 standups, 2 one-to-ones (one of them moved), dentist, the UTC call, the recruiter call, the monthly review
    assert data["calendars"] == [{"name": "personal", "events": 13, "blocking_next_14_days": 11}]
    assert SAMPLE not in text and "Dentist" not in text


def test_schemas_describe_the_same_tools():
    names = [t["name"] for t in tools.TOOLS]
    assert names == ["free_slots", "status", "check_calendars"]
    assert [f["function"]["name"] for f in tools.openai_schema()] == names
    assert tools.openai_schema()[0]["function"]["parameters"]["additionalProperties"] is False


# ---------- whenfree call and whenfree schema ----------

def test_call_from_a_shell(capsys):
    assert cli.main(["call", "free_slots", "--args", '{"days": "2026-10-07"}']) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["data"]["days"][0]["free"] == [["10:15", "12:00"], ["13:00", "16:00"]]
    assert cli.main(["call", "free_slots", "--args", '{"days": "nonsense"}']) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and "could not read any date" in out["error"]
    assert cli.main(["call", "free_slots", "--args", "{not json"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_schema_command(capsys):
    assert cli.main(["schema"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["inputSchema"]["type"] == "object"
    assert cli.main(["schema", "--format", "openai"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["type"] == "function"


# ---------- the MCP server ----------

def talk(*messages):
    stdin = io.StringIO("".join(json.dumps(m) + "\n" for m in messages))
    stdout = io.StringIO()
    assert mcp.serve(stdin, stdout) == 0
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def test_mcp_handshake_and_tool_list():
    answers = talk(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "ping"},
    )
    assert len(answers) == 3                                         # the notification gets no answer
    init = answers[0]["result"]
    assert init["protocolVersion"] == "2025-03-26" and init["serverInfo"]["name"] == "when-free"
    assert init["capabilities"] == {"tools": {"listChanged": False}}
    assert [t["name"] for t in answers[1]["result"]["tools"]] == ["free_slots", "status", "check_calendars"]
    assert answers[2] == {"jsonrpc": "2.0", "id": 3, "result": {}}


def test_mcp_offers_the_newest_version_it_knows_for_an_unknown_one():
    (answer,) = talk({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})
    assert answer["result"]["protocolVersion"] == mcp.PROTOCOLS[0]


def test_mcp_tool_call():
    (answer,) = talk({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                      "params": {"name": "free_slots", "arguments": {"days": "2026-10-07"}}})
    result = answer["result"]
    assert result["isError"] is False
    assert "- Wed 7 Oct: 10:15–12:00, 13:00–16:00" in result["content"][0]["text"]
    assert result["structuredContent"]["days"][0]["free"] == [["10:15", "12:00"], ["13:00", "16:00"]]


def test_mcp_a_failed_tool_is_a_result_the_model_can_read():
    (answer,) = talk({"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                      "params": {"name": "free_slots", "arguments": {"days": "2026-09-01"}}})
    assert answer["result"]["isError"] is True and "past" in answer["result"]["content"][0]["text"]


def test_mcp_protocol_errors():
    answers = talk({"jsonrpc": "2.0", "id": 9, "method": "resources/list"}, {"id": 10, "method": "ping"})
    assert answers[0]["error"]["code"] == -32601 and answers[1]["error"]["code"] == -32600
    stdout = io.StringIO()
    mcp.serve(io.StringIO("this is not json\n\n"), stdout)
    assert json.loads(stdout.getvalue())["error"]["code"] == -32700


def test_mcp_writes_only_protocol_lines(capsys):
    talk({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "free_slots", "arguments": {}}})
    assert capsys.readouterr().out == ""                             # nothing leaks to the real stdout
