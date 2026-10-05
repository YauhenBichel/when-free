"""Status right now, status bars, phones (pairing, page, calendar feed), QR codes and the calendar cache."""
import datetime as dt
import json
import pathlib
import stat
import struct
import threading
import urllib.error
import urllib.request
import zlib
from zoneinfo import ZoneInfo

import pytest

from whenfree import api, cli
from whenfree.agents import tools
from whenfree.calendars import cache
from whenfree.core import slots, status
from whenfree.devices import feed, pairing, qr, widgets
from whenfree.web import server

SAMPLE = str(pathlib.Path(__file__).parent / "data" / "sample.ics")
TZ = ZoneInfo("Europe/London")
at = lambda d, h, m=0: dt.datetime(2026, 10, d, h, m, tzinfo=TZ)
busy = lambda d, h1, m1, h2, m2: slots.Busy(at(d, h1, m1), at(d, h2, m2))


@pytest.fixture(autouse=True)
def fixed_world(tmp_path, monkeypatch):
    settings = tmp_path / "config.toml"
    settings.write_text(f'hours = "10:00-16:00"\n[[calendar]]\nname = "personal"\npath = "{SAMPLE}"\n')
    monkeypatch.setenv("WHENFREE_CONFIG", str(settings))
    monkeypatch.setenv("WHENFREE_NOW", "2026-10-01T11:30:00")             # Thursday, in the dentist (11:00-12:00)
    monkeypatch.setenv("WHENFREE_TZ", "Europe/London")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("WHENFREE_CALENDARS", raising=False)
    monkeypatch.delenv("WHENFREE_TOKEN", raising=False)
    return tmp_path


# ---------- the status right now ----------

def test_busy_until_follows_events_that_run_on():
    blocks = [busy(1, 10, 0, 11, 0), busy(1, 11, 0, 11, 30), busy(1, 13, 0, 14, 0)]
    assert status.busy_until(blocks, at(1, 10, 15)) == at(1, 11, 30)
    assert status.busy_until(blocks, at(1, 12, 0)) is None
    assert status.free_until(blocks, at(1, 12, 0), TZ) == at(1, 13)


def test_next_free_skips_the_weekend():
    full_friday = [busy(2, 9, 0, 18, 0)]
    start, _ = status.next_free(full_friday, at(2, 9, 30), TZ, dt.time(9), dt.time(18), buffer_minutes=0,
                                min_minutes=60, weekends=False)
    assert start == at(5, 9)


def test_status_from_the_calendar():
    st = api.status()
    assert st["free_now"] is False and st["busy_until"] == "2026-10-01T12:00+01:00"
    assert st["next_free"]["start"] == "12:15" and st["today"] == [["12:15", "16:00"]]
    assert "Dentist" not in json.dumps(st)


def test_the_status_tool():
    text, data = tools.call("status")
    assert text.splitlines()[0] == "Busy until 12:00 · next free 12:15–16:00" and data["free_now"] is False


# ---------- status bars ----------

@pytest.mark.parametrize("fmt", widgets.FORMATS)
def test_every_status_bar_format(capsys, fmt):
    assert cli.main(["now", "--format", fmt, "--cache", "0"]) == 0
    out = capsys.readouterr().out
    assert "12:00" in out and "Dentist" not in out


def test_waybar_is_json_with_a_class(capsys):
    cli.main(["now", "--format", "waybar"])
    bar = json.loads(capsys.readouterr().out)
    assert bar["class"] == "busy" and bar["text"] == "busy → 12:00" and "Today" in bar["tooltip"]


def test_a_problem_is_never_shown_as_free(capsys):
    assert cli.main(["now", "--format", "waybar", "--calendar", "/no/such.ics"]) == 0      # the bar keeps running
    bar = json.loads(capsys.readouterr().out)
    assert bar["class"] == "error" and "free" not in bar["text"]
    assert cli.main(["now", "--calendar", "/no/such.ics"]) == 1


# ---------- the calendar cache ----------

def test_memory_cache_reuses_a_fresh_copy():
    calls, clock = [], [0.0]
    reader = cache.MemoryCache(300, lambda s: calls.append(s) or "text", clock=lambda: clock[0])
    reader("https://x/a.ics"), reader("https://x/a.ics")
    clock[0] = 301
    reader("https://x/a.ics")
    assert len(calls) == 2


def test_disk_cache_is_private_and_never_names_the_address(fixed_world):
    calls = []
    reader = cache.DiskCache(300, lambda s: calls.append(s) or "BEGIN:VCALENDAR")
    secret = "https://calendar.example/private-SECRET/basic.ics"
    assert reader(secret) == reader(secret) == "BEGIN:VCALENDAR" and len(calls) == 1
    files = list(cache.cache_dir().iterdir())
    assert len(files) == 1 and "SECRET" not in files[0].name
    assert stat.S_IMODE(files[0].stat().st_mode) == 0o600 and stat.S_IMODE(cache.cache_dir().stat().st_mode) == 0o700


# ---------- QR codes ----------

@pytest.mark.parametrize("length, size", [(1, 21), (14, 21), (15, 25), (100, 41), (213, 57)])
def test_qr_picks_the_smallest_version(length, size):
    assert len(qr.encode("x" * length, "M")) == size


def test_qr_has_finder_patterns_and_refuses_what_does_not_fit():
    m = qr.encode("http://192.168.1.20:8765/m#t=abc")
    n = len(m)
    for x0, y0 in ((0, 0), (n - 7, 0), (0, n - 7)):
        assert all(m[y0][x0 + i] for i in range(7)) and not m[y0 + 1][x0 + 1] and m[y0 + 3][x0 + 3]
    with pytest.raises(ValueError):
        qr.encode("x" * 300, "M")


def test_qr_png_is_a_valid_png():
    data = qr.to_png(qr.encode("hello"), scale=2, border=1)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    assert width == height == (21 + 2) * 2
    assert zlib.crc32(data[12:29]) == struct.unpack(">I", data[29:33])[0]


# ---------- the calendar feed ----------

def test_the_feed_holds_free_slots_only():
    result = api.find_free(api.Query(days="2026-10-01, 2026-10-07"))
    text = feed.calendar(result, host="test")
    assert text.count("BEGIN:VEVENT") == sum(len(d["free"]) for d in result["days"]) == 3
    assert "SUMMARY:Free" in text and "TRANSP:TRANSPARENT" in text and "Dentist" not in text
    assert "DTSTART:20261001T111500Z" in text                              # 12:15 in London is 11:15 UTC
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))


# ---------- pairing ----------

def test_devices_are_kept_as_hashes(fixed_world):
    store = pairing.Devices(fixed_world / "devices.json")
    device, token = store.add("  Alex's   iPhone ")
    assert device.name == "Alex's iPhone" and token not in (fixed_world / "devices.json").read_text()
    assert stat.S_IMODE((fixed_world / "devices.json").stat().st_mode) == 0o600
    assert store.find(token).name == "Alex's iPhone" and store.find("nope") is None and store.find("") is None
    with pytest.raises(Exception):
        store.add("alex's iphone")
    store.remove("ALEX'S IPHONE")
    assert store.find(token) is None


def test_devices_command(capsys, fixed_world):
    assert cli.main(["devices", "add", "Tablet", "--url", "http://10.0.0.5:8765"]) == 0
    out = capsys.readouterr()
    assert "\033[30;107m" in out.out                                       # the QR code
    assert "http://10.0.0.5:8765/m#t=" in out.err and "webcal://10.0.0.5:8765/free.ics?t=" in out.err
    assert cli.main(["devices", "list"]) == 0 and "Tablet" in capsys.readouterr().out
    assert cli.main(["devices", "remove", "Tablet"]) == 0


# ---------- the server, as a phone sees it ----------

@pytest.fixture
def phone(fixed_world):
    device, device_token = pairing.Devices(pairing.store_path()).add("Phone")
    srv = server.make_server(port=0, token="owner-token")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.base_url, device_token
    srv.shutdown()
    srv.server_close()


def get(url, token=None, data=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), e.headers


def test_the_page_needs_no_token_and_is_locked_down(phone):
    url, _ = phone
    status_code, body, headers = get(url + "/m")
    assert status_code == 200 and "app.js" in body
    assert "script-src 'self'" in headers["Content-Security-Policy"] and headers["Referrer-Policy"] == "no-referrer"
    assert get(url + "/app.js")[0] == 200 and get(url + "/manifest.webmanifest")[0] == 200


def test_a_device_sees_free_time_and_status_only(phone):
    url, token = phone
    assert json.loads(get(url + "/status", token)[1])["data"]["free_now"] is False
    assert get(url + "/free_slots", token, {"days": "2026-10-07"})[0] == 200
    assert get(url + "/free_slots", token, {"days": "2026-10-07", "include_busy": True})[0] == 403
    assert get(url + "/check_calendars", token, {})[0] == 403
    assert get(url + "/check_calendars", "owner-token", {})[0] == 200
    assert get(url + "/status.txt", token)[1] == "Busy until 12:00 · next free 12:15–16:00\n"


def test_the_feed_takes_the_token_in_the_address(phone):
    url, token = phone
    code, body, headers = get(f"{url}/free.ics?t={token}")
    assert code == 200 and headers["Content-Type"].startswith("text/calendar") and "BEGIN:VCALENDAR" in body
    assert get(f"{url}/free.ics?t=wrong")[0] == 401
    assert get(f"{url}/status?t={token}")[0] == 401                         # only the feed reads it from the address


def test_a_removed_device_is_refused_at_once(phone):
    url, token = phone
    pairing.Devices(pairing.store_path()).remove("Phone")
    assert get(url + "/status", token)[0] == 401
