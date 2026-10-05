# when-free on your other devices

Your calendar stays on your computer. Other devices ask it, each in the way it already understands:

| Device | How it connects | Protocol |
|---|---|---|
| [iPhone, iPad, Android phones and tablets](#phones-and-tablets) | A page you add to the home screen, and/or a calendar subscription | HTTP(S), iCalendar |
| [Apple Watch, Wear OS watches](#phones-and-tablets) | Through the phone's calendar | iCalendar |
| [Home Assistant, and through it Alexa, Google Home, Apple Home, Assist](#smart-home-and-voice) | Entities that appear by themselves | MQTT with Home Assistant discovery, or HTTP |
| [Busy lights, door signs, any MQTT device](#smart-home-and-voice) | Retained topics | MQTT |
| [macOS menu bar](#desktop-status-bars) | SwiftBar or xbar plugin | `whenfree now` |
| [Linux bars: Waybar, i3blocks, Polybar, GNOME](#desktop-status-bars) | A module that runs a command | `whenfree now` |
| [Windows notification area](#desktop-status-bars) | A PowerShell tray script | `whenfree now` |

**What a device sees:** whether you're free now, until when, and your free slots. **Never** event titles or calendar details. When a calendar can't be read, devices show "unknown" or "unavailable", never "free".

## Phones and tablets

**1. On your computer, start the server for your home network:**

```bash
whenfree serve --lan
```

**2. Pair the phone.** In another terminal:

```bash
whenfree devices add "Alex's iPhone"
```

A QR code appears. Point the phone's camera at it. The page that opens shows whether you're free now and your coming days, and you can paste a message to get the slots for it. Add it to the home screen (Safari: Share → *Add to Home Screen*; Chrome: ⋮ → *Add to Home screen*) and it opens like an app.

**3. Optional: your free slots in the phone's own calendar.** The same command also prints a `webcal://…/free.ics?t=…` address. On iPhone, open it in Safari and confirm. On Android, add it in Google Calendar on the web (*Other calendars* → *From URL*). Watches show it through the phone. Run `whenfree devices add "Phone calendar" --show calendar` to get it as a QR code instead.

**Each device has its own token.** It's shown only once and stored only as a hash. To see or remove devices:

```bash
whenfree devices list
whenfree devices remove "Alex's iPhone"       # its token stops working at once
```

**Away from home.** The phone has to reach your computer. The simplest and safest way is [Tailscale](https://tailscale.com) on both, then pair with the computer's Tailscale name: `whenfree devices add "Phone" --url http://my-mac:8765`. Tailscale encrypts the traffic. Don't forward the port on your router.

**Encryption at home.** On your own Wi-Fi the traffic is plain HTTP, protected by the token. For HTTPS, pass a certificate: `whenfree serve --lan --tls-cert cert.pem --tls-key key.pem`, and pair with `--url https://...`. `tailscale cert` makes a certificate phones trust.

## Smart home and voice

**Home Assistant with MQTT** (the Mosquitto add-on is enough):

```bash
WHENFREE_MQTT_PASSWORD=... whenfree mqtt --broker mqtt://whenfree@homeassistant.local
```

A device called **when-free** appears in Home Assistant with:

| Entity | Example |
|---|---|
| `binary_sensor.when_free_free_now` | on / off |
| `sensor.when_free_status` | Busy until 15:30 · next free 15:45–17:00 |
| `sensor.when_free_busy_until`, `sensor.when_free_free_until`, `sensor.when_free_next_free` | timestamps |
| `sensor.when_free_today` | 14:15–18:00 |

From there:

- **A busy light** at the door, a quieter doorbell during meetings, a dashboard card: see [`integrations/homeassistant/examples.yaml`](../integrations/homeassistant/examples.yaml).
- **Voice.** *"Is Alex free?"* works with Home Assistant's Assist using the example's custom sentences. For **Alexa**, **Google Home** or **Siri/Apple Home**, expose `binary_sensor.when_free_free_now` to them in Home Assistant (Settings → Voice assistants → Expose).
- **Other MQTT devices** (an ESP32 door sign, a Node-RED flow): subscribe to `whenfree/<computer>/state`. It's retained JSON with `free_now`, `status`, `busy_until`, `free_until`, `next_free` and `today`. `whenfree/<computer>/availability` is `online` or `offline`.

Options: `--interval 60` (seconds between checks), `--topic whenfree`, `--node my_mac`, `--discovery-prefix homeassistant`, and `mqtts://` for TLS. `--once` publishes once and stops, to try it out. The password is read only from `WHENFREE_MQTT_PASSWORD`, never from the command line. To keep it running, use the `launchd` or `systemd` set-up in the [recipes](recipes.md#start-the-server-at-login) with `mqtt --broker ...` instead of `serve`.

**Without MQTT:** pair Home Assistant as a device and use a REST sensor on `/status`. There's an example at the end of the same file.

## Desktop status bars

`whenfree now` prints the status right now, in the shape each bar wants:

```console
$ whenfree now
Busy until 15:30 · next free 15:45–17:00
```

| Bar | Set up |
|---|---|
| **macOS menu bar** ([SwiftBar](https://swiftbar.app) or [xbar](https://xbarapp.com)) | Copy [`integrations/swiftbar/when-free.1m.sh`](../integrations/swiftbar/when-free.1m.sh) into the plugin folder |
| **GNOME** ([Argos](https://github.com/p-e-w/argos)) | The same file, in `~/.config/argos/` |
| **Waybar** | [`integrations/waybar/config.jsonc`](../integrations/waybar/config.jsonc) and [`style.css`](../integrations/waybar/style.css) |
| **i3blocks**, Polybar, tmux | [`integrations/i3blocks/when-free.conf`](../integrations/i3blocks/when-free.conf) |
| **Windows** notification area | [`integrations/windows/when-free-tray.ps1`](../integrations/windows/when-free-tray.ps1). Not yet tested on Windows; reports welcome |
| Anything else | `whenfree now --format json` or `--format text` |

Formats: `text`, `json`, `waybar`, `i3blocks`, `polybar`, `xbar`, `tmux`. Status bars run the command every minute, so calendars are kept for 5 minutes (`--cache MINUTES`; `0` fetches every time). The cached copies are in `~/.cache/when-free`, readable only by you, and named by a hash, never by the calendar's address.
