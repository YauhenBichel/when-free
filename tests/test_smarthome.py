"""MQTT packets, and what Home Assistant receives."""
import json
import pathlib
import socket
import threading

import pytest

from whenfree import api
from whenfree.smarthome import homeassistant, mqtt

SAMPLE = str(pathlib.Path(__file__).parent / "data" / "sample.ics")


@pytest.fixture(autouse=True)
def fixed_world(tmp_path, monkeypatch):
    monkeypatch.setenv("WHENFREE_CONFIG", str(tmp_path / "none.toml"))
    monkeypatch.setenv("WHENFREE_NOW", "2026-10-01T11:30:00")
    monkeypatch.setenv("WHENFREE_TZ", "Europe/London")
    monkeypatch.setenv("WHENFREE_CALENDARS", SAMPLE)


def test_connect_packet_matches_the_specification():
    # MQTT 3.1.1, 3.1: protocol name, level 4, flags, keep-alive, then the payload fields in order.
    packet = mqtt.connect_packet("id", 60, "user", "pw", will=("t/a", b"offline", True))
    assert packet[0] == 0x10
    body = packet[2:]
    assert body[:6] == b"\x00\x04MQTT" and body[6] == 4
    assert body[7] == 0x80 | 0x40 | 0x20 | 0x04 | 0x02 and body[8:10] == b"\x00\x3c"
    assert body[10:] == b"\x00\x02id" + b"\x00\x03t/a" + b"\x00\x07offline" + b"\x00\x04user" + b"\x00\x02pw"


def test_long_payloads_use_a_multi_byte_length():
    packet = mqtt.publish_packet("t", b"x" * 200, retain=True)
    assert packet[0] == 0x31 and packet[1:3] == bytes([0xCB, 0x01])        # 203 = 0x4B + 1 * 128


@pytest.mark.parametrize("address, expected", [
    ("homeassistant.local", ("homeassistant.local", 1883, None, False)),
    ("mqtt://me@10.0.0.2:1884", ("10.0.0.2", 1884, "me", False)),
    ("mqtts://broker.example", ("broker.example", 8883, None, True)),
])
def test_broker_addresses(address, expected):
    b = mqtt.Broker.parse(address)
    assert (b.host, b.port, b.username, b.tls) == expected


def test_a_password_in_the_address_is_refused():
    with pytest.raises(mqtt.MqttError):
        mqtt.Broker.parse("mqtt://me:secret@host")


class FakeClient:
    def __init__(self):
        self.sent, self.will, self.pings = [], None, 0

    def connect(self, will=None):
        self.will = will

    def publish(self, topic, payload, retain=False):
        self.sent.append((topic, payload, retain))

    def ping(self):
        self.pings += 1

    def disconnect(self):
        pass


def test_home_assistant_discovers_the_entities_and_reads_the_state():
    client, topics = FakeClient(), homeassistant.Topics(node="mac")
    pub = homeassistant.Publisher(client, topics, lambda: api.status())
    pub.start()
    assert client.will == ("whenfree/mac/availability", b"offline", True)
    configs = {t: json.loads(p) for t, p, r in client.sent if t.endswith("/config") and r}
    assert "homeassistant/binary_sensor/mac/free_now/config" in configs
    assert all(c["state_topic"] == "whenfree/mac/state" for c in configs.values())
    assert configs["homeassistant/sensor/mac/busy_until/config"]["device_class"] == "timestamp"
    assert pub.tick() == "Busy until 12:00 · next free 12:15–18:00"
    state = json.loads(next(p for t, p, r in client.sent if t == "whenfree/mac/state"))
    assert state["free_now"] is False and state["busy_until"] == "2026-10-01T12:00:00+01:00"
    assert ("whenfree/mac/availability", "online", True) in client.sent
    assert "Dentist" not in json.dumps(state)


def test_an_unchanged_state_is_not_published_again():
    client = FakeClient()
    pub = homeassistant.Publisher(client, homeassistant.Topics(node="mac"), lambda: api.status())
    pub.tick()
    sent = len(client.sent)
    assert pub.tick() == "" and len(client.sent) == sent and client.pings == 1


def test_an_unreadable_calendar_makes_it_unavailable_not_free(monkeypatch):
    monkeypatch.setenv("WHENFREE_CALENDARS", "/no/such.ics")
    client = FakeClient()
    pub = homeassistant.Publisher(client, homeassistant.Topics(node="mac"), lambda: api.status())
    assert pub.tick().startswith("unavailable")
    assert client.sent == [("whenfree/mac/availability", "offline", True)]


def test_the_client_talks_to_a_broker():
    """A tiny broker on a socket: CONNACK, then PINGRESP. Checks the bytes on the wire."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    seen = []

    def broker():
        conn, _ = listener.accept()
        with conn:
            seen.append(conn.recv(1024))
            conn.sendall(b"\x20\x02\x00\x00")
            data = b""
            while b"\xc0\x00" not in data:
                data += conn.recv(1024)
            seen.append(data)
            conn.sendall(b"\xd0\x00")
            seen.append(conn.recv(1024))

    thread = threading.Thread(target=broker, daemon=True)
    thread.start()
    client = mqtt.Client(mqtt.Broker("127.0.0.1", listener.getsockname()[1]), "test")
    client.connect()
    client.publish("a/b", "hi", retain=True)
    client.ping()
    client.disconnect()
    thread.join(timeout=5)
    listener.close()
    assert seen[0][0] == 0x10 and seen[1].startswith(b"\x31\x07\x00\x03a/bhi") and seen[2] == b"\xe0\x00"


def test_a_refused_connection_says_why():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)

    def broker():
        conn, _ = listener.accept()
        with conn:
            conn.recv(1024)
            conn.sendall(b"\x20\x02\x00\x04")

    threading.Thread(target=broker, daemon=True).start()
    with pytest.raises(mqtt.MqttError, match="user name or password"):
        mqtt.Client(mqtt.Broker("127.0.0.1", listener.getsockname()[1]), "test").connect()
    listener.close()
