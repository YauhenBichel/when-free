"""The three ways an agent reaches when-free: the Python function, `whenfree call`, and the MCP server."""
import io
import json
import pathlib

import pytest

from whenfree import api, cli
from whenfree import mcp, tools

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
    assert names[:3] == ["free_slots", "status", "check_calendars"]
    assert "gmail_search" in names and "slack_post" in names and "teams_post" in names
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
    assert [t["name"] for t in answers[1]["result"]["tools"]] == [t["name"] for t in tools.TOOLS]
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


# ---------- calendars and questions that are wrong, or strange ----------

def calendar_with(tmp_path, *lines, name="odd.ics"):
    path = tmp_path / name
    path.write_text("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:x\r\nSUMMARY:Board meeting\r\n" + "\r\n".join(lines)
                    + "\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nUID:ok\r\nSUMMARY:Fine\r\nDTSTART:20261007T100000Z\r\n"
                      "DTEND:20261007T110000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    return str(path)


def test_an_event_that_cannot_be_read_is_named_and_the_rest_still_answers(tmp_path, monkeypatch):
    odd = calendar_with(tmp_path, "DTSTART:garbage", "DTEND:20261007T150000Z")
    monkeypatch.setenv("WHENFREE_CALENDARS", odd)
    text, data = tools.call("free_slots", {"days": "2026-10-07"})
    assert data["days"][0]["free"] == [["12:15", "16:00"]]         # the event that could be read still blocks
    note, = data["notes"]
    assert "calendar 'calendar 1'" in note and "'Board meeting'" in note and "DTSTART" in note
    assert f"Note: {note}" in text
    text, data = tools.call("check_calendars", {})
    assert data["notes"] == [note] and f"Note: {note}" in text


def test_a_rule_that_names_no_day_does_not_hang_and_blocks_its_first_date(tmp_path, monkeypatch):
    odd = calendar_with(tmp_path, "DTSTART:20261006T100000Z", "DTEND:20261006T110000Z", "RRULE:FREQ=MONTHLY;BYMONTHDAY=0")
    monkeypatch.setenv("WHENFREE_CALENDARS", odd)
    result = api.find_free(api.Query(days="2026-10-06"))
    assert result["days"][0]["free"] == [["12:15", "16:00"]]
    assert "calendar 'calendar 1'" in result["notes"][0] and "only its first date is counted" in result["notes"][0]


def test_the_buffer_reaches_across_midnight(tmp_path, monkeypatch):
    late = calendar_with(tmp_path, "DTSTART:20261005T220000Z", "DTEND:20261005T225500Z")      # ends 23:55 in London
    monkeypatch.setenv("WHENFREE_CALENDARS", late)
    result = api.find_free(api.Query(days="2026-10-06", hours="00:00-03:00", buffer_minutes=15, min_minutes=15))
    assert result["days"][0]["free"] == [["00:10", "03:00"]]


def test_a_range_too_long_to_answer_is_refused_with_the_setting_named(tmp_path, monkeypatch):
    with pytest.raises(api.Problem) as e:
        api.find_free(api.Query(end="9999-12-31"))
    assert "max_range_days" in str(e.value) and "366" in str(e.value)
    with pytest.raises(api.Problem):
        api.find_free(api.Query(days="9999-12-31"))                 # the last day there is: no day after it
    with pytest.raises(api.Problem) as e:
        api.find_free(api.Query(days="2026-10-07, 2028-10-07"))
    assert "max_range_days" in str(e.value)
    settings = pathlib.Path(tmp_path / "config.toml")
    settings.write_text(settings.read_text().replace("hours =", "max_range_days = 800\nhours ="))
    assert len(api.find_free(api.Query(end="2028-01-31"))["days"]) > 300


def test_a_range_of_weekend_days_says_so():
    with pytest.raises(api.Problem) as e:
        api.find_free(api.Query(start="2026-10-03", end="2026-10-04"))
    assert "Saturday and Sunday" in str(e.value) and "--weekends" in str(e.value) and "past" not in str(e.value)
    assert len(api.find_free(api.Query(start="2026-10-03", end="2026-10-04", weekends=True))["days"]) == 2


def test_part_of_a_date_that_was_not_read_is_a_note_not_a_silence():
    text, data = tools.call("free_slots", {"days": "5 Oct, 7"})
    assert [d["date"] for d in data["days"]] == ["2026-10-05"]
    assert "'7'" in data["notes"][0] and "was not read" in data["notes"][0] and "Note: " in text
    assert tools.call("free_slots", {"days": "Oct 5, 6, 7"})[1]["notes"] == []


def test_last_friday_is_refused_as_past_not_answered_for_next_friday():
    with pytest.raises(api.Problem) as e:
        api.find_free(api.Query(days="last Friday"))
    assert "past" in str(e.value)


def test_what_was_sent_is_not_sent_back_whole():
    with pytest.raises(api.Problem) as e:
        api.find_free(api.Query(days="A" * 100_000))
    assert len(str(e.value)) < 400
    with pytest.raises(api.Problem) as e:
        tools.call("free_slots", {"B" * 100_000: 1})
    assert len(str(e.value)) < 400
    with pytest.raises(api.Problem) as e:
        tools.call("C" * 100_000, {})
    assert "C" * 60 not in str(e.value)


# ---------- an MCP client that sends the wrong thing ----------

def call(id_=1, **extra):
    return {"jsonrpc": "2.0", "id": id_, **extra}


@pytest.mark.parametrize("message, code", [
    (call(method="tools/call", params=[1, 2]), -32602),
    (call(method="tools/call", params="free_slots"), -32602),
    (call(method="initialize", params=["2025-06-18"]), -32602),
    (call(method="tools/call", params={"name": 5}), -32602),
    (call(method="tools/call", params={"name": ["free_slots"]}), -32602),
    (call(method="tools/call", params={"arguments": {}}), -32602),
    (call(method=["tools/list"]), -32600),
    (call(method={"a": 1}), -32600),
    (call(method=5), -32600),
    (call(id_={"a": 1}, method="ping"), -32600),
    (call(id_=[1], method="ping"), -32600),
])
def test_mcp_answers_a_wrong_message_with_an_error_and_stays_up(message, code):
    wrong, after = talk(message, call(id_=2, method="ping"))
    assert wrong["error"]["code"] == code
    assert after == {"jsonrpc": "2.0", "id": 2, "result": {}}        # the next message is still answered


def test_mcp_survives_a_message_nested_too_deep_and_bytes_that_are_not_text():
    stdout = io.StringIO()
    stdin = io.TextIOWrapper(io.BytesIO(("[" * 100_000 + "\n").encode() + b'\xff\xfe{"jsonrpc"\n'
                                        + json.dumps(call(method="ping")).encode() + b"\n"),
                             encoding="utf-8", errors="replace")
    assert mcp.serve(stdin, stdout) == 0
    deep, garbled, ping = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert deep["error"]["code"] == -32600 and garbled["error"]["code"] == -32700 and ping["result"] == {}


def test_mcp_survives_a_tool_that_breaks_in_a_new_way(monkeypatch):
    def broken(params, config_path):
        raise RuntimeError("address=https://calendar.example/SECRET")
    monkeypatch.setitem(mcp.METHODS, "ping", broken)
    wrong, after = talk(call(method="ping"), call(id_=2, method="tools/list"))
    assert wrong["error"]["code"] == -32603 and "SECRET" not in json.dumps(wrong)
    assert "tools" in after["result"]


def test_mcp_does_not_echo_a_huge_argument():
    answer, = talk(call(method="tools/call", params={"name": "free_slots", "arguments": {"days": "A" * 1_000_000}}))
    assert answer["result"]["isError"] and len(json.dumps(answer)) < 2000


def test_tools_declare_the_arguments_they_cannot_work_without():
    required = {t["name"]: t["inputSchema"].get("required", []) for t in tools.TOOLS}
    assert required["gmail_draft"] == ["to", "subject", "body"] and required["slack_post"] == ["channel", "text"]
    assert required["github_comment"] == ["owner", "repo", "number", "body"] and required["notion_read"] == ["id"]
    assert required["free_slots"] == [] and required["status"] == [] and required["slack_channels"] == []
    for t in tools.TOOLS:                                           # never a name the schema does not describe
        assert set(required[t["name"]]) <= set(t["inputSchema"]["properties"])
