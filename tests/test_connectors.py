"""Connector tools talk to a stand-in HTTP call. No test reaches Google, Slack or Microsoft."""
import json
import os
import stat

import pytest

from whenfree.connect import http, store
from whenfree.core.errors import Problem
from whenfree.tools import registry


@pytest.fixture(autouse=True)
def no_network():
    yield
    http.install(None)


def test_a_missing_login_names_the_command(tmp_path):
    with pytest.raises(Problem) as e:
        registry.call("gmail_search", {"query": "hello"}, config_path=str(tmp_path / "config.toml"))
    assert "whenfree connect google" in str(e.value)


def test_gmail_search_returns_the_subject(tmp_path):
    def transport(method, url, headers, body):
        if "/messages?" in url:
            return 200, b'{"messages":[{"id":"abc"}]}'
        return 200, json.dumps({
            "id": "abc", "threadId": "thr",
            "payload": {"headers": [{"name": "Subject", "value": "Hello"}, {"name": "From", "value": "a@b.c"}]},
        }).encode()

    http.install(transport)
    store.write("google-token.json", str(tmp_path / "config.toml"), {"access_token": "ya29-secret"})
    text, data = registry.call("gmail_search", {"query": "hello"}, config_path=str(tmp_path / "config.toml"))
    assert data["messages"][0]["subject"] == "Hello"
    assert "ya29-secret" not in text


def test_a_slack_error_does_not_repeat_the_token(tmp_path):
    http.install(lambda method, url, headers, body: (200, b'{"ok": false, "error": "not_in_channel", "token": "xoxb-secret"}'))
    store.write("slack-token.json", str(tmp_path / "config.toml"), {"access_token": "xoxb-secret"})
    with pytest.raises(Problem) as e:
        registry.call("slack_post", {"channel": "C0123", "text": "hi"}, config_path=str(tmp_path / "config.toml"))
    assert "not_in_channel" in str(e.value) and "xoxb-secret" not in str(e.value)


def test_a_draft_is_not_a_send(tmp_path):
    sent = []

    def transport(method, url, headers, body):
        sent.append(url)
        return 200, b'{"id": "d1"}'

    http.install(transport)
    store.write("google-token.json", str(tmp_path / "config.toml"), {"access_token": "ya29-secret"})
    text, data = registry.call(
        "gmail_draft", {"to": "a@b.c", "subject": "Hi", "body": "There"},
        config_path=str(tmp_path / "config.toml"),
    )
    assert data["sent"] is False and "not sent" in text
    assert sent == ["https://gmail.googleapis.com/gmail/v1/users/me/drafts"]


def test_the_token_file_is_private(tmp_path):
    path = store.write("slack-token.json", str(tmp_path / "config.toml"), {"access_token": "xoxb-secret"})
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_connected_accounts_names_no_token(tmp_path):
    text, data = registry.call("connected_accounts", {}, config_path=str(tmp_path / "config.toml"))
    assert all(row["connected"] is False for row in data["accounts"])
    assert "secret" not in text
