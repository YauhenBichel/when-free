import json
import pathlib

import pytest

from whenfree import cli

SAMPLE = str(pathlib.Path(__file__).parent / "data" / "sample.ics")


@pytest.fixture(autouse=True)
def fixed_world(tmp_path, monkeypatch):
    monkeypatch.setenv("WHENFREE_CONFIG", str(tmp_path / "config.toml"))      # no settings file
    monkeypatch.setenv("WHENFREE_NOW", "2026-10-01T08:00:00")
    monkeypatch.setenv("WHENFREE_TZ", "Europe/London")
    monkeypatch.delenv("WHENFREE_CALENDARS", raising=False)


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_a_week_of_slots(capsys):
    code, out, err = run(capsys, "--calendar", SAMPLE, "--from", "2026-10-01", "--to", "2026-10-07", "--hours", "10:00-16:00")
    assert code == 0
    assert out.splitlines() == [
        "- Thu 1 Oct: 12:15–16:00",
        "- Fri 2 Oct: 10:15–13:45",
        "- Mon 5 Oct: 10:00–14:45",
        "- Tue 6 Oct: 10:00–13:45",          # no `me` is set, so the invitation someone declined still blocks 14:00
        "- Wed 7 Oct: 10:15–12:00, 13:00–16:00",
    ]
    assert "Europe/London" in err             # the context is on stderr, so stdout can be pasted into a reply


def test_settings_file_supplies_the_calendar_and_my_address(capsys, tmp_path, monkeypatch):
    path = tmp_path / "settings.toml"
    path.write_text(f'hours = "10:00-16:00"\nme = ["me@example.com"]\n[[calendar]]\nname = "personal"\npath = "{SAMPLE}"\n')
    monkeypatch.setenv("WHENFREE_CONFIG", str(path))
    code, out, _ = run(capsys, "--days", "Tue 6 Oct")
    assert code == 0 and out.splitlines() == ["- Tue 6 Oct: 10:00–14:45"]      # my declined invitation no longer blocks


def test_slots_is_the_default_command_and_the_next_working_days_the_default_range(capsys):
    code, out, _ = run(capsys, "--calendar", SAMPLE)
    days = [line.split(":")[0] for line in out.splitlines()]
    assert code == 0 and days == ["- Thu 1 Oct", "- Fri 2 Oct", "- Mon 5 Oct", "- Tue 6 Oct", "- Wed 7 Oct", "- Thu 8 Oct", "- Fri 9 Oct"]


def test_reads_days_and_hours_from_a_message(capsys, tmp_path):
    message = tmp_path / "message.txt"
    message.write_text("Could you do Wednesday 30th, Thursday 1st or Friday 2nd, between 10:00am and 4:00pm?")
    code, out, err = run(capsys, "--calendar", SAMPLE, "--message", str(message))
    assert code == 0
    assert out.splitlines() == ["- Thu 1 Oct: 12:15–16:00", "- Fri 2 Oct: 10:15–13:45"]
    assert "Wed 30 Sep" in err and "pattern matching" in err       # yesterday is reported, not silently dropped


def test_json(capsys):
    code, out, _ = run(capsys, "--calendar", SAMPLE, "--days", "Wed 7 Oct", "--hours", "10:00-16:00", "--format", "json")
    data = json.loads(out)
    assert code == 0 and data["timezone"] == "Europe/London"
    assert data["days"] == [{"date": "2026-10-07", "free": [["10:15", "12:00"], ["13:00", "16:00"]]}]


def test_busy_lists_what_blocks(capsys):
    _, out, _ = run(capsys, "--calendar", SAMPLE, "--days", "Thu 1 Oct", "--busy")
    assert "busy 11:00–12:00  Dentist" in out


def test_without_a_calendar_it_explains_the_setup(capsys):
    code, out, err = run(capsys)
    assert code == 1 and out == "" and "whenfree init" in err


def test_an_unreadable_calendar_prints_no_slots_and_no_address(capsys):
    secret = "/no/such/place/SECRET-TOKEN.ics"
    code, out, err = run(capsys, "--calendar", secret, "--calendar", SAMPLE)
    assert code == 1 and out == ""
    assert "SECRET-TOKEN" not in err and "busy time would look free" in err


def test_dates_in_the_past(capsys):
    code, _, err = run(capsys, "--calendar", SAMPLE, "--days", "Mon 28 Sep")
    assert code == 1 and "past" in err


def test_init_and_check(capsys, tmp_path):
    path = tmp_path / "new" / "config.toml"
    code, out, _ = run(capsys, "init", "--config", str(path))
    assert code == 0 and path.exists() and str(path) in out
    code, _, err = run(capsys, "init", "--config", str(path))
    assert code == 1 and "already exists" in err
    code, out, _ = run(capsys, "check", "--calendar", SAMPLE)
    assert code == 0 and "13 events" in out
