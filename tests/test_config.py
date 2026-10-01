import stat
import tomllib

import pytest

from whenfree import config


def test_defaults_when_there_is_no_file(tmp_path, monkeypatch):
    monkeypatch.delenv("WHENFREE_CALENDARS", raising=False)
    cfg = config.load(tmp_path / "missing.toml")
    assert (cfg.hours, cfg.min_minutes, cfg.buffer_minutes, cfg.days_ahead) == ("09:00-18:00", 60, 15, 7)
    assert cfg.calendars == [] and cfg.extract_command is None


def test_reads_a_settings_file(tmp_path, monkeypatch):
    monkeypatch.delenv("WHENFREE_CALENDARS", raising=False)
    path = tmp_path / "config.toml"
    path.write_text('''
timezone = "Europe/Berlin"
hours = "10:00-16:00"
min_minutes = 45
me = ["me@example.com"]
[[calendar]]
name = "personal"
url = "https://example.com/a.ics"
[[calendar]]
path = "~/work.ics"
[[calendar]]
name = "empty one is ignored"
url = ""
[extract]
command = ["ollama", "run", "llama3.2"]
''')
    cfg = config.load(path)
    assert cfg.timezone == "Europe/Berlin" and cfg.min_minutes == 45 and cfg.me == ["me@example.com"]
    assert [(c.name, c.source) for c in cfg.calendars] == [("personal", "https://example.com/a.ics"), ("calendar 2", "~/work.ics")]
    assert cfg.extract_command == ["ollama", "run", "llama3.2"]


def test_environment_replaces_the_calendar_list(tmp_path, monkeypatch):
    monkeypatch.setenv("WHENFREE_CALENDARS", "/a.ics, /b.ics")
    cfg = config.load(tmp_path / "missing.toml")
    assert [c.source for c in cfg.calendars] == ["/a.ics", "/b.ics"]


@pytest.mark.parametrize("body", ['min_minutes = "sixty"', 'weekends = 1', 'timezone = "Mars/Olympus"', "buffer_minutes = -5",
                                  "this is not toml"])
def test_mistakes_are_reported(tmp_path, monkeypatch, body):
    monkeypatch.delenv("WHENFREE_CALENDARS", raising=False)
    path = tmp_path / "config.toml"
    path.write_text(body)
    with pytest.raises(config.ConfigError):
        config.load(path)


def test_init_writes_a_private_file_once(tmp_path):
    path = config.write_template(tmp_path / "nested" / "config.toml")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600        # it will hold secret calendar addresses
    assert tomllib.loads(path.read_text())["hours"] == "09:00-18:00"
    assert config.load(path).calendars == []                 # the empty url in the template is not a calendar
    with pytest.raises(config.ConfigError):
        config.write_template(path)
