# Recipes

Small set-ups that put when-free one keystroke away. Each assumes you've installed it and added a calendar ([README](../README.md#add-your-calendar)).

- [Claude Desktop, in one click](#claude-desktop-in-one-click)
- [Raycast](#raycast)
- [macOS: right-click a message, get your slots](#macos-right-click-a-message-get-your-slots)
- [Open WebUI](#open-webui)
- [n8n, Make, Zapier-style tools](#n8n-and-other-workflow-tools)
- [iPhone and Mac Shortcuts](#iphone-and-mac-shortcuts)

## Claude Desktop, in one click

1. Download `when-free.mcpb` from the [latest release](https://github.com/YauhenBichel/when-free/releases/latest).
2. Double-click it. Claude Desktop shows what it does and asks to install it.
3. In its settings, paste your calendar's private address into **Calendar addresses** (several, separated by commas). Claude Desktop keeps it in your system's secure storage. If you already ran `whenfree add`, leave it empty.

Claude Desktop runs it with its own copy of Python, so you don't need to install anything else. Then ask: *"Am I free on Thursday afternoon?"*

## Raycast

Two [script commands](https://github.com/raycast/script-commands) are in [`integrations/raycast`](../integrations/raycast):

| Command | What it does |
|---|---|
| **When am I free** | Asks for days (`next week`, `tomorrow`, `Thu 15 Oct`) and hours (`afternoon`, `10:00-16:00`), both optional. Shows your slots and copies them |
| **When am I free for this message** | Reads the message on your clipboard, shows the slots for the days it asks about, and puts them on the clipboard |

Raycast → Settings → Extensions → **+** → *Add Script Directory* → choose `integrations/raycast`.

## macOS: right-click a message, get your slots

A Quick Action that works on text selected in Mail, Messages, Safari or anywhere else:

1. Open **Shortcuts**, make a new shortcut, and in its details turn on **Use as Quick Action** and **Services Menu**. Set it to receive **Text**.
2. Add **Run Shell Script**. Shell: `zsh`. Pass input: **to stdin**. Script:

   ```bash
   export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
   whenfree --message -
   ```

3. Add **Copy to Clipboard**, then **Show Notification** with the shell script result.

Select the recruiter's message, right-click, *Services* → your shortcut, and paste the answer into your reply.

## Open WebUI

Open WebUI can call a tool server from your browser (a tool server you add under your own *Settings*) or from its own server (one an admin adds under *Admin Settings*).

**From your browser.** The page calls when-free directly, so allow its address:

```bash
whenfree serve --allow-origin http://localhost:3000        # your Open WebUI address
```

Then Settings → **Tools** → add a tool server. URL: `http://127.0.0.1:8765`. Auth: **Bearer**, with the contents of `~/.config/when-free/token`.

**From Open WebUI's server, in Docker.** Inside the container, `127.0.0.1` is the container itself, so when-free has to listen beyond it:

```bash
whenfree serve --host 0.0.0.0
```

Admin Settings → **Tools** → URL `http://host.docker.internal:8765`, with the same bearer token. This makes when-free reachable from your network, protected by the token. Do it only on a network you trust.

Then turn the tool on in a chat and ask: *"When am I free next week for 90 minutes?"* To start the server at login, see [below](#start-the-server-at-login).

## n8n and other workflow tools

Use an **HTTP Request** node:

- Method `POST`, URL `http://127.0.0.1:8765/free_slots`
- Header `Authorization: Bearer <token>`
- JSON body, for example `{"message": "{{ $json.text }}", "min_minutes": 60}`

The response's `text` is ready to put in a reply, and `data.days[].free` holds the same slots as data. If `ok` is false, `error` says why. Don't send a reply with guessed times.

## iPhone and Mac Shortcuts

**Get Contents of URL** with `http://<your-computer>:8765/free_slots?days=tomorrow`, header `Authorization: Bearer <token>`, then **Get Dictionary Value** `text`. For a phone, the server has to listen beyond `127.0.0.1`. Do that only on a network you trust.

## Start the server at login

macOS (`~/Library/LaunchAgents/com.github.yauhenbichel.when-free.plist`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.github.yauhenbichel.when-free</string>
  <key>ProgramArguments</key><array><string>/Users/YOU/.local/bin/whenfree</string><string>serve</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.github.yauhenbichel.when-free.plist
```

Linux (`~/.config/systemd/user/when-free.service`):

```ini
[Unit]
Description=when-free

[Service]
ExecStart=%h/.local/bin/whenfree serve
Restart=on-failure

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now when-free
```
