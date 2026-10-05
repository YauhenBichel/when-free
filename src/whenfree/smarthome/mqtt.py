"""Just enough MQTT 3.1.1 to publish, standard library only: connect (with a last will), publish, ping, disconnect.

QoS 0 throughout: the states are retained and republished every few minutes, so a lost message is replaced soon.
"""
from __future__ import annotations

import socket
import ssl
import struct
from dataclasses import dataclass

REFUSED = {
    1: "the broker does not speak MQTT 3.1.1",
    2: "the broker refused the client id",
    3: "the broker is unavailable",
    4: "the user name or password is wrong",
    5: "not authorised",
}


class MqttError(Exception):
    pass


def _length(n: int) -> bytes:
    out = bytearray()
    while True:
        byte, n = n % 128, n // 128
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _string(value: str | bytes) -> bytes:
    data = value.encode() if isinstance(value, str) else value
    return struct.pack(">H", len(data)) + data


def _packet(kind: int, body: bytes) -> bytes:
    return bytes([kind]) + _length(len(body)) + body


def connect_packet(client_id: str, keepalive: int, username: str | None = None, password: str | None = None,
                   will: tuple[str, bytes, bool] | None = None) -> bytes:
    flags = 0x02                                       # clean session
    payload = _string(client_id)
    if will:
        topic, message, retain = will
        flags |= 0x04 | (0x20 if retain else 0)
        payload += _string(topic) + _string(message)
    if username is not None:
        flags |= 0x80
        payload += _string(username)
        if password is not None:
            flags |= 0x40
            payload += _string(password)
    return _packet(0x10, _string("MQTT") + bytes([4, flags]) + struct.pack(">H", keepalive) + payload)


def publish_packet(topic: str, payload: bytes, retain: bool = False) -> bytes:
    return _packet(0x30 | (0x01 if retain else 0), _string(topic) + payload)


@dataclass
class Broker:
    host: str
    port: int = 1883
    username: str | None = None
    password: str | None = None
    tls: bool = False

    @classmethod
    def parse(cls, address: str, password: str | None = None) -> Broker:
        """mqtt://user@host:1883, mqtts://host (TLS, port 8883), or host[:port]."""
        import urllib.parse
        if "://" not in address:
            address = "mqtt://" + address
        url = urllib.parse.urlsplit(address)
        if url.scheme not in ("mqtt", "mqtts", "tcp", "ssl"):
            raise MqttError(f"unknown scheme {url.scheme!r}: use mqtt:// or mqtts://")
        tls = url.scheme in ("mqtts", "ssl")
        if not url.hostname:
            raise MqttError("the broker address has no host, like mqtt://homeassistant.local")
        if url.password:
            raise MqttError("do not put the password in the address; set WHENFREE_MQTT_PASSWORD instead")
        return cls(url.hostname, url.port or (8883 if tls else 1883), url.username or None, password, tls)


class Client:
    def __init__(self, broker: Broker, client_id: str, keepalive: int = 60, timeout: float = 10):
        self.broker, self.client_id, self.keepalive, self.timeout = broker, client_id, keepalive, timeout
        self.sock: socket.socket | None = None

    def connect(self, will: tuple[str, bytes, bool] | None = None) -> None:
        b = self.broker
        try:
            sock = socket.create_connection((b.host, b.port), timeout=self.timeout)
            if b.tls:
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=b.host)
        except OSError as e:
            raise MqttError(f"cannot reach the broker at {b.host}:{b.port} ({e.strerror or e})") from None
        self.sock = sock
        self._send(connect_packet(self.client_id, self.keepalive, b.username, b.password, will))
        head = self._read(4)
        if head[0] != 0x20:
            raise MqttError("the broker did not answer like an MQTT broker")
        if head[3] != 0:
            raise MqttError(f"the broker refused the connection: {REFUSED.get(head[3], f'code {head[3]}')}")

    def publish(self, topic: str, payload: str | bytes, retain: bool = False) -> None:
        self._send(publish_packet(topic, payload.encode() if isinstance(payload, str) else payload, retain))

    def ping(self) -> None:
        """Keep the connection alive, and wait for the answer: everything sent before it has then arrived."""
        self._send(b"\xc0\x00")
        for _ in range(16):
            if self._read_packet()[0] == 0xD0:
                return
        raise MqttError("the broker did not answer a ping")

    def _read_packet(self) -> tuple[int, bytes]:
        """One whole packet: (type byte, body)."""
        kind = self._read(1)[0]
        length, shift = 0, 0
        while True:
            byte = self._read(1)[0]
            length |= (byte & 0x7F) << shift
            shift += 7
            if not byte & 0x80:
                break
        return kind & 0xF0, self._read(length) if length else b""

    def disconnect(self) -> None:
        if self.sock:
            try:
                self._send(b"\xe0\x00")
            except MqttError:
                pass
            self.sock.close()
            self.sock = None

    def _send(self, data: bytes) -> None:
        if self.sock is None:
            raise MqttError("not connected")
        try:
            self.sock.sendall(data)
        except OSError as e:
            raise MqttError(f"lost the broker ({e.strerror or e})") from None

    def _read(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            try:
                chunk = self.sock.recv(n - len(data))
            except OSError as e:
                raise MqttError(f"lost the broker ({e.strerror or e})") from None
            if not chunk:
                raise MqttError("the broker closed the connection")
            data += chunk
        return data
