# Changelog

## Unreleased

Setting up a calendar without editing a file, and messages that say "next week".

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
  next to the settings file, readable only by you, or `WHENFREE_TOKEN`), requests addressed to another host
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
