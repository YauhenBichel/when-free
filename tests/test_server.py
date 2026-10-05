"""`whenfree serve`: the same tools over local HTTP, behind a token."""
import json
import os
import pathlib
import stat
import threading
import urllib.error
import urllib.request

import pytest

from whenfree.agents import tools
from whenfree.web import server

SAMPLE = str(pathlib.Path(__file__).parent / "data" / "sample.ics")
TOKEN = "test-token"


@pytest.fixture
def url(tmp_path, monkeypatch):
    settings = tmp_path / "config.toml"
    settings.write_text(f'hours = "10:00-16:00"\n[[calendar]]\nname = "personal"\npath = "{SAMPLE}"\n')
    monkeypatch.setenv("WHENFREE_CONFIG", str(settings))
    monkeypatch.setenv("WHENFREE_NOW", "2026-10-01T08:00:00")
    monkeypatch.setenv("WHENFREE_TZ", "Europe/London")
    monkeypatch.delenv("WHENFREE_CALENDARS", raising=False)
    srv = server.make_server(port=0, token=TOKEN, origins=["http://localhost:3000"])
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.base_url
    srv.shutdown()
    srv.server_close()


def ask(url, path, body=None, token=TOKEN, headers=None, method=None):
    h = dict(headers or {})
    if token:
        h["Authorization"] = f"Bearer {token}"
    data = None if body is None else json.dumps(body).encode()
    if data is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None), r.headers
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, (json.loads(raw) if raw else None), e.headers


def test_post_a_tool_call(url):
    status, body, _ = ask(url, "/free_slots", {"days": "2026-10-07"})
    assert status == 200 and body["ok"]
    assert body["data"]["days"][0]["free"] == [["10:15", "12:00"], ["13:00", "16:00"]]
    assert "- Wed 7 Oct: 10:15–12:00, 13:00–16:00" in body["text"]


def test_get_with_a_query_string(url):
    status, body, _ = ask(url, "/free_slots?days=2026-10-07&min_minutes=120&include_busy=true")
    assert status == 200
    assert body["data"]["days"][0]["free"] == [["13:00", "16:00"]] and "busy" in body["data"]["days"][0]


def test_a_problem_is_a_400_with_the_reason(url):
    status, body, _ = ask(url, "/free_slots", {"days": "nonsense"})
    assert status == 400 and body["ok"] is False and "could not read any date" in body["error"]
    status, body, _ = ask(url, "/free_slots?min_minutes=lots")
    assert status == 400 and "should be integer" in body["error"]


@pytest.mark.parametrize("token", [None, "wrong"])
def test_tools_need_the_token(url, token):
    status, body, headers = ask(url, "/free_slots", {"days": "2026-10-07"}, token=token)
    assert status == 401 and headers["WWW-Authenticate"] == "Bearer" and "data" not in body


def test_health_and_openapi_need_no_token(url):
    assert ask(url, "/health", token=None)[1]["name"] == "when-free"
    status, spec, _ = ask(url, "/openapi.json", token=None)
    assert status == 200 and spec["openapi"].startswith("3.1")
    assert sorted(spec["paths"]) == sorted(f"/{t['name']}" for t in tools.TOOLS)
    op = spec["paths"]["/free_slots"]["post"]
    assert op["operationId"] == "free_slots"
    assert op["requestBody"]["content"]["application/json"]["schema"] == tools.TOOLS[0]["inputSchema"]
    assert spec["servers"] == [{"url": url}]


def test_a_request_for_another_host_is_refused(url):
    # A web page that points its own name at 127.0.0.1 sends its own name as Host.
    status, body, _ = ask(url, "/free_slots", {"days": "2026-10-07"}, headers={"Host": "evil.example"})
    assert status == 403 and "data" not in body
    assert ask(url, "/health", token=None, headers={"Host": "localhost:9"})[0] == 200


def test_cross_origin_only_for_allowed_origins(url):
    status, _, headers = ask(url, "/free_slots", token=None, method="OPTIONS",
                             headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"})
    assert status == 204 and headers["Access-Control-Allow-Origin"] == "http://localhost:3000"
    assert "Authorization" in headers["Access-Control-Allow-Headers"]
    status, _, headers = ask(url, "/free_slots", token=None, method="OPTIONS", headers={"Origin": "https://evil.example"})
    assert status == 403 and headers.get("Access-Control-Allow-Origin") is None
    _, _, headers = ask(url, "/free_slots", {"days": "2026-10-07"}, headers={"Origin": "https://evil.example"})
    assert headers.get("Access-Control-Allow-Origin") is None


def test_unknown_path_and_bad_json(url):
    assert ask(url, "/book_meeting", {})[0] == 404
    req = urllib.request.Request(url + "/free_slots", data=b"{nope", method="POST",
                                 headers={"Authorization": f"Bearer {TOKEN}"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 400


def test_the_token_is_made_once_and_kept_private(tmp_path, monkeypatch):
    monkeypatch.delenv("WHENFREE_TOKEN", raising=False)
    cfg = str(tmp_path / "config.toml")
    first, where = server.load_token(cfg)
    assert where == str(tmp_path / "token") and len(first) >= 24
    assert stat.S_IMODE(os.stat(where).st_mode) == 0o600
    assert server.load_token(cfg)[0] == first
    monkeypatch.setenv("WHENFREE_TOKEN", "from-env")
    assert server.load_token(cfg) == ("from-env", "WHENFREE_TOKEN")


def test_on_another_address_the_token_alone_protects_it(tmp_path, monkeypatch):
    # Open WebUI in Docker calls host.docker.internal; that is only possible when listening beyond loopback.
    monkeypatch.setenv("WHENFREE_CONFIG", str(tmp_path / "none.toml"))
    srv = server.make_server(host="0.0.0.0", port=0, token=TOKEN)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        local = f"http://127.0.0.1:{srv.server_address[1]}"
        assert ask(local, "/health", token=None, headers={"Host": "host.docker.internal:8765"})[0] == 200
        assert ask(local, "/check_calendars", {}, token=None, headers={"Host": "host.docker.internal"})[0] == 401
    finally:
        srv.shutdown()
        srv.server_close()
