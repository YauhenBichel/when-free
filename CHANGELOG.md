# Changelog

## Unreleased

## 0.4.1 (2026-10-09)

Friendlier in Claude Code.

- No calendar yet? The message now gives the command that works for uvx and Claude Code plugin installs:
  `uvx when-free add`. The skill stops there instead of looking for your calendar in other tools.
- The skill answers in one line per day with the time zone once, and when you paste someone's message it
  ends with a reply you can send.
- The skill names the real `free_slots` arguments, so the agent gets it right on the first call.

## 0.4.0 (2026-10-08)

On your other devices: phones and tablets, Home Assistant and voice assistants, desktop status bars.

- `whenfree now`: free or busy right now, until when, and the next free slot, formatted for SwiftBar/xbar/Argos,
  Waybar, i3blocks, Polybar, tmux, plain text or JSON. Calendars are kept for 5 minutes between runs, in
  `~/.cache/when-free`, readable only by you and named by a hash. An unreadable calendar shows as "?", never free.
  Plug-ins in `integrations/` for the macOS menu bar, Linux bars and the Windows notification area.
- A `status` tool for agents and over HTTP (`/status`, and `/status.txt` as one line of text).
- Phones and tablets: `whenfree serve --lan` and `whenfree devices add NAME`, which shows a QR code. Each device
  has its own token, kept only as a hash and revocable with `whenfree devices remove`. A device sees free time and
  the status, never event titles (403). The phone page at `/m` installs to the home screen, answers pasted
  messages and works in light and dark mode. `/free.ics` is your free slots as a calendar that phones, tablets and
  watches can subscribe to. `--tls-cert` and `--tls-key` serve HTTPS.
- Smart homes: `whenfree mqtt --broker ...` publishes to MQTT with Home Assistant discovery (free now, status,
  busy until, free until, next free, free today). From Home Assistant it reaches Alexa, Google Home, Apple Home
  and Assist. The device goes unavailable when a calendar cannot be read. Examples for a busy light, voice and a
  dashboard are in `integrations/homeassistant/examples.yaml`.
- `whenfree serve` keeps calendars for 5 minutes, so phones and dashboards that ask often do not fetch them each
  time.
- A Claude Code plugin: the MCP server plus a skill that tells Claude when to use it
  (`/plugin marketplace add YauhenBichel/when-free`, then `/plugin install when-free@when-free`).

## 0.3.0 (2026-10-05)

Easier to start and to reach from other tools: on PyPI, a Claude Desktop extension, a local HTTP server,
a demo, and messages that say "next week".

- On PyPI: `uvx when-free demo` runs it with nothing installed, and `uv tool install when-free` keeps it.
  The package also installs a `when-free` command, so MCP clients can start it with `uvx when-free mcp`.
- `when-free.mcpb`, a Claude Desktop extension, is attached to each release. Claude Desktop provides Python,
  and asks for the calendar address as a sensitive setting kept in the system's secure storage.
- Listed in the MCP registry as `io.github.YauhenBichel/when-free` (`server.json`, published by the release
  workflow with GitHub OIDC).
- Recipes for Raycast (two script commands in `integrations/raycast`), a macOS right-click Quick Action,
  Open WebUI, n8n, Shortcuts, and starting the server at login: `docs/recipes.md`.

- A message, `--days` and the `days` tool argument now understand days relative to today when no explicit date
  is given: "today", "tomorrow", "Thursday" (the coming one), "this Tuesday", "next Tuesday" (of next week),
  "next week", "this week", "the week after next", "Tuesday or Wednesday next week". Explicit dates still win,
  so a "Next week:" heading over dated lines adds nothing.
- "morning", "afternoon" and "evening" give the hours (09:00–12:00, 12:00–17:00, 17:00–20:00) when none are
  stated, in a message or in `--hours`. "Good morning" is a greeting and is ignored.
- `whenfree demo` answers a recruiter's message from a made-up calendar for next week, in your time zone, so
  you can see what it does before adding a calendar. It reads no settings, fetches nothing and saves nothing.
- The README starts with a demo GIF, a one-minute try, and three steps to add a calendar; tools are chosen
  from one table; troubleshooting and reference are folded away.
- `whenfree serve`: a local HTTP server for tools that cannot start a command (Open WebUI, n8n, Shortcuts,
  Raycast, scripts). `POST /free_slots` and `/check_calendars` with JSON, or `GET` with a query string; an
  OpenAPI 3.1 description at `/openapi.json`. It listens on 127.0.0.1, every tool call needs a token (kept
  next to the settings file, readable only by you, or `WHENFREE_TOKEN`), requests addressed to another host (when on 127.0.0.1)
  are refused, and a web page may call it only from an origin given with `--allow-origin`.

- `whenfree add` asks for a calendar's private address at a prompt that does not show it (or reads it from
  standard input: `pbpaste | whenfree add`), reads the calendar, and saves it in the settings file only if
  that worked. It creates the file if there is none, fills in the empty block of a new file, and adds later
  calendars as new blocks; the rest of the file is left as it is. `whenfree add FILE` adds an exported file.
- A calendar that cannot be read now says more when it can tell why: Google's public address given instead of
  the secret one, an address that was refused and is probably incomplete, a web page instead of a feed.
- "No calendar is configured" names the settings file when the file exists but holds no address, and points
  to `whenfree add`.
- The settings template and `whenfree init` no longer say to replace `webcal://` with `https://`; such an
  address has always worked as it is.

## 0.2.0 (2026-10-01)

For assistants and agents. Nothing changes for the command line.

- `whenfree mcp`: a Model Context Protocol server on standard input and output, standard library only,
  with two read-only tools, `free_slots` and `check_calendars`.
- `whenfree schema` prints the tool definitions (MCP shape or `--format openai`), and
  `whenfree call NAME --args JSON` runs a tool from a shell with JSON in and JSON out.
- `whenfree.api.find_free(Query(...))` is the one function behind the command line, the MCP server
  and `call`. It returns plain data and raises `api.Problem` with a message that is safe to show.
- Event titles are left out of tool results unless the caller asks with `include_busy`.

## 0.1.0 (2026-10-01)

- `whenfree` prints the free slots for the next working days, a date range, or named days.
- `whenfree --message` reads the proposed days and hours out of a pasted message by pattern matching,
  or with a model you run yourself through the optional `[extract]` command.
- `whenfree init` creates the settings file with owner-only permissions; `whenfree check` reads every
  configured calendar and says what it found.
- Reads iCalendar feeds and files with the standard library only: time zones, events marked Free,
  cancelled events, declined invitations, whole-day events, and repeating events (daily, weekly,
  monthly by date or by "first Monday", yearly) with skipped and moved occurrences.
- Prints no slots at all when a calendar cannot be read, and never prints a calendar's address.
