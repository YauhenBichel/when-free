"""`whenfree add`: the calendar is read first, saved only if that worked, and its address is never shown."""
import io
import pathlib
import stat
import urllib.error

import pytest

from whenfree import cli
from whenfree import settings as config
from whenfree.calendars import sources

SAMPLE = str(pathlib.Path(__file__).parent / "data" / "sample.ics")
SECRET = "https://calendar.google.com/calendar/ical/me%40example.com/private-SECRET-TOKEN/basic.ics"


@pytest.fixture(autouse=True)
def fixed_world(tmp_path, monkeypatch):
    monkeypatch.setenv("WHENFREE_CONFIG", str(tmp_path / "config.toml"))      # no settings file yet
    monkeypatch.setenv("WHENFREE_NOW", "2026-10-01T08:00:00")
    monkeypatch.setenv("WHENFREE_TZ", "Europe/London")
    monkeypatch.delenv("WHENFREE_CALENDARS", raising=False)


@pytest.fixture
def online(monkeypatch):
    """Every address answers with the sample calendar; nothing touches the network."""
    monkeypatch.setattr(sources, "read", lambda source: pathlib.Path(SAMPLE).read_text())


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def paste(monkeypatch, text):
    monkeypatch.setattr("sys.stdin", io.StringIO(text))          # as in: pbpaste | whenfree add


def test_a_pasted_address_is_checked_saved_and_never_shown(capsys, tmp_path, monkeypatch, online):
    paste(monkeypatch, SECRET + "\n")
    code, out, err = run(capsys, "add")
    path = tmp_path / "config.toml"
    assert code == 0 and "Added 'personal': 13 events" in out and str(path) in out
    assert "SECRET-TOKEN" not in out + err
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    cfg = config.load(path)
    assert [(c.name, c.source) for c in cfg.calendars] == [("personal", SECRET)]
    assert cfg.hours == "09:00-18:00" and "# when-free settings" in path.read_text()     # the rest of the template is kept


def test_at_a_terminal_the_address_is_asked_for_without_echo(capsys, tmp_path, monkeypatch, online):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("getpass.getpass", lambda prompt: f'  "{SECRET}"  ')           # pasted with quotes and spaces
    code, out, err = run(capsys, "add", "--name", "work")
    assert code == 0 and "Secret address in iCal format" in err and "SECRET-TOKEN" not in out + err
    assert [(c.name, c.source) for c in config.load().calendars] == [("work", SECRET)]


def test_it_fills_the_empty_block_of_a_new_settings_file_then_appends(capsys, tmp_path, monkeypatch, online):
    path = config.write_template()
    path.write_text(path.read_text().replace("me = []", 'me = ["me@example.com"]'))
    paste(monkeypatch, SECRET)
    assert run(capsys, "add")[0] == 0
    assert path.read_text().splitlines().count("[[calendar]]") == 1     # the placeholder was filled in, not left behind
    code, out, _ = run(capsys, "add", SAMPLE)                      # a file is given as an argument; it is no secret
    assert code == 0 and "Added 'calendar 2'" in out
    cfg = config.load(path)
    assert [(c.name, c.source) for c in cfg.calendars] == [("personal", SECRET), ("calendar 2", SAMPLE)]
    assert cfg.me == ["me@example.com"] and stat.S_IMODE(path.stat().st_mode) == 0o600


def test_nothing_is_saved_when_the_calendar_cannot_be_read(capsys, tmp_path, monkeypatch):
    paste(monkeypatch, "/no/such/place/SECRET-TOKEN.ics")
    code, out, err = run(capsys, "add")
    assert code == 1 and out == "" and "Nothing was saved" in err and "SECRET-TOKEN" not in err
    assert not (tmp_path / "config.toml").exists()


def test_a_name_cannot_be_used_twice(capsys, monkeypatch):
    assert run(capsys, "add", SAMPLE, "--name", "work")[0] == 0
    code, _, err = run(capsys, "add", SAMPLE, "--name", "work")
    assert code == 1 and "already has a calendar named 'work'" in err
    assert len(config.load().calendars) == 1


@pytest.mark.parametrize("pasted", ["", "   \n", "two\nlines", "https://example.com/a b.ics"])
def test_what_is_not_one_address_is_refused(capsys, tmp_path, monkeypatch, pasted):
    paste(monkeypatch, pasted)
    code, _, err = run(capsys, "add")
    assert code == 1 and "not one address" in err and not (tmp_path / "config.toml").exists()


def test_an_address_on_the_command_line_works_but_is_warned_about(capsys, online):
    code, out, err = run(capsys, "add", SECRET)
    assert code == 0 and "shell history" in err and "SECRET-TOKEN" not in out + err


def test_a_file_is_saved_with_its_full_path(capsys, tmp_path, monkeypatch):
    (tmp_path / "work.ics").write_text(pathlib.Path(SAMPLE).read_text())
    monkeypatch.chdir(tmp_path)
    assert run(capsys, "add", "work.ics")[0] == 0
    assert config.load().calendars[0].source == str(tmp_path / "work.ics")


def test_a_block_in_use_is_never_overwritten(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[[calendar]]\nname = "family"\nurl = ""\npath = "/family.ics"\n')      # an empty url beside a real path
    assert config.add_calendar("/b.ics", path=path)[1] == "personal"
    assert [(c.name, c.source) for c in config.load(path).calendars] == [("family", "/family.ics"), ("personal", "/b.ics")]


def test_other_settings_and_tables_are_left_as_they_are(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('hours = "10:00-16:00"   # mine\n[[calendar]]\nname = "personal"\npath = "/a.ics"\n\n'
                    '[extract]\ncommand = ["ollama", "run", "llama3.2"]\n')
    assert config.add_calendar("webcal://example.com/b.ics", path=path) == (path, "calendar 2")
    cfg = config.load(path)
    assert [(c.name, c.source) for c in cfg.calendars] == [("personal", "/a.ics"), ("calendar 2", "webcal://example.com/b.ics")]
    assert cfg.extract_command == ["ollama", "run", "llama3.2"] and "# mine" in path.read_text()


# ---------- what `check` says when a calendar cannot be read ----------

def refuse(monkeypatch, code):
    def read(source):
        raise urllib.error.HTTPError("https://hidden", code, {404: "Not Found", 500: "Server Error"}[code], None, None)
    monkeypatch.setattr(sources, "read", read)


def test_googles_public_address_is_named_as_the_mistake(capsys, monkeypatch):
    refuse(monkeypatch, 404)
    public = "https://calendar.google.com/calendar/ical/me%40example.com/public/basic.ics"
    code, _, err = run(capsys, "check", "--calendar", public)
    assert code == 1 and "public address" in err and "Secret address in iCal format" in err and "me%40example" not in err


def test_a_refused_address_is_probably_incomplete_but_a_server_fault_is_not(capsys, monkeypatch):
    refuse(monkeypatch, 404)
    assert "part of it may be missing" in run(capsys, "check", "--calendar", SECRET)[2]
    refuse(monkeypatch, 500)
    code, _, err = run(capsys, "check", "--calendar", SECRET)
    assert code == 1 and "part of it may be missing" not in err and "SECRET-TOKEN" not in err


def test_a_web_page_is_not_a_calendar(capsys, monkeypatch):
    monkeypatch.setattr(sources, "read", lambda source: "<!DOCTYPE html>\n<html><body>Sign in</body></html>")
    code, _, err = run(capsys, "check", "--calendar", SECRET)
    assert code == 1 and "returned a web page" in err and ".ics" in err


def test_an_empty_settings_file_is_named(capsys):
    path = config.write_template()
    code, _, err = run(capsys, "check")
    assert code == 1 and str(path) in err and "whenfree add" in err
