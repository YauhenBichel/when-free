# Changelog

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
