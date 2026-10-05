"""Publish whether you are free to an MQTT broker, with Home Assistant discovery.

    whenfree mqtt --broker mqtt://homeassistant.local

Home Assistant finds a device called "when-free" with these entities, and from there they reach dashboards,
automations (a busy light at the door), Alexa, Google Home and Apple Home through Home Assistant's own bridges,
and Home Assistant's voice assistant:

    binary_sensor.when_free_free_now      on when you are not in an event
    sensor.when_free_status               "Busy until 15:30 · next free 15:45–17:00"
    sensor.when_free_busy_until           when the current event ends (a timestamp)
    sensor.when_free_free_until           when the next event today starts (a timestamp)
    sensor.when_free_next_free            when the next free slot starts (a timestamp)
    sensor.when_free_today                what is left free today, like "14:15–18:00"

No event titles are published. When a calendar cannot be read the device goes unavailable, never "free".
"""
from __future__ import annotations

import json
import socket
import sys
import time
from collections.abc import Callable

from .. import __version__, api
from ..core import render
from .mqtt import Client, MqttError

ENTITIES = [
    # (component, key, name, extra config)
    ("binary_sensor", "free_now", "Free now",
     {"value_template": "{{ 'ON' if value_json.free_now else 'OFF' }}", "icon": "mdi:calendar-check"}),
    ("sensor", "status", "Status", {"value_template": "{{ value_json.status }}", "icon": "mdi:calendar-clock"}),
    ("sensor", "busy_until", "Busy until",
     {"value_template": "{{ value_json.busy_until or None }}", "device_class": "timestamp"}),
    ("sensor", "free_until", "Free until",
     {"value_template": "{{ value_json.free_until or None }}", "device_class": "timestamp"}),
    ("sensor", "next_free", "Next free",
     {"value_template": "{{ value_json.next_free or None }}", "device_class": "timestamp"}),
    ("sensor", "today", "Free today", {"value_template": "{{ value_json.today }}", "icon": "mdi:calendar-today"}),
]


class Topics:
    def __init__(self, base: str = "whenfree", node: str | None = None, discovery: str = "homeassistant"):
        self.node = node or "when_free_" + "".join(c if c.isalnum() else "_" for c in socket.gethostname().lower())
        self.base = f"{base.rstrip('/')}/{self.node}"
        self.discovery = discovery.rstrip("/")
        self.state = f"{self.base}/state"
        self.availability = f"{self.base}/availability"

    def config(self, component: str, key: str) -> str:
        return f"{self.discovery}/{component}/{self.node}/{key}/config"


def discovery_configs(topics: Topics) -> dict[str, dict]:
    device = {"identifiers": [topics.node], "name": "when-free", "manufacturer": "when-free",
              "model": "calendar availability", "sw_version": __version__}
    out = {}
    for component, key, name, extra in ENTITIES:
        out[topics.config(component, key)] = {
            "name": name, "unique_id": f"{topics.node}_{key}", "object_id": f"when_free_{key}",
            "state_topic": topics.state, "availability_topic": topics.availability,
            "payload_available": "online", "payload_not_available": "offline",
            "device": device, **extra,
        }
    return out


def state_payload(st: dict) -> dict:
    """What every entity reads its value from. Timestamps carry seconds and the zone, as Home Assistant wants."""
    full = lambda iso: iso[:16] + ":00" + iso[16:] if iso and iso[16:17] != ":" else iso     # 11:30+01:00 -> 11:30:00+01:00
    return {
        "free_now": st["free_now"],
        "status": render.status_line(st),
        "busy_until": full(st["busy_until"]),
        "free_until": full(st["free_until"]),
        "next_free": full(st["next_free"]["starts"]) if st["next_free"] else None,
        "today": ", ".join(f"{a}–{b}" for a, b in st["today"]) or "none",
        "updated": full(st["now"]),
    }


class Publisher:
    """Connects, announces the entities, then publishes the state whenever it changes (and every few minutes)."""

    def __init__(self, client: Client, topics: Topics, status: Callable[[], dict], *, interval: float = 60,
                 refresh: float = 600, log=None):
        self.client, self.topics, self.status = client, topics, status
        self.interval, self.refresh = interval, refresh
        self.log = log or (lambda text: print(text, file=sys.stderr))
        self._last: tuple[str, float] | None = None

    def start(self) -> None:
        self.client.connect(will=(self.topics.availability, b"offline", True))
        for topic, config in discovery_configs(self.topics).items():
            self.client.publish(topic, json.dumps(config), retain=True)

    def tick(self) -> str:
        """Publish once. Returns what was published, for the log."""
        try:
            payload = json.dumps(state_payload(self.status()), ensure_ascii=False)
        except api.Problem as e:
            # Unknown is unavailable, never free.
            self.client.publish(self.topics.availability, "offline", retain=True)
            self._last = None
            return f"unavailable: {str(e).splitlines()[0]}"
        now = time.monotonic()
        if self._last is None or self._last[0] != payload or now - self._last[1] >= self.refresh:
            self.client.publish(self.topics.state, payload, retain=True)
            self.client.publish(self.topics.availability, "online", retain=True)
            self._last = (payload, now)
            return json.loads(payload)["status"]
        self.client.ping()
        return ""

    def run(self, once: bool = False) -> int:
        delay = 5
        while True:
            try:
                self.start()
                self.log(f"Publishing to {self.topics.base} (Home Assistant discovery under {self.topics.discovery}/)")
                delay = 5
                while True:
                    said = self.tick()
                    if said:
                        self.log(said)
                    if once:
                        self.client.ping()            # waits for the broker, so nothing is lost on the way out
                        self.client.disconnect()
                        return 0
                    time.sleep(self.interval)
            except MqttError as e:
                if once:
                    raise
                self.log(f"{e}; trying again in {delay} s")
                self.client.disconnect()
                time.sleep(delay)
                delay = min(delay * 2, 300)
            except KeyboardInterrupt:
                try:
                    self.client.publish(self.topics.availability, "offline", retain=True)
                except MqttError:
                    pass
                self.client.disconnect()
                return 0
