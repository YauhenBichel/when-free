# when-free

**Which days and times am I free?**
Someone asks for your availability. This reads your calendars and prints the slots you can offer, ready to paste into the reply.

[![tests](https://github.com/YauhenBichel/when-free/actions/workflows/tests.yml/badge.svg)](https://github.com/YauhenBichel/when-free/actions/workflows/tests.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

A recruiter writes: *"Please share your availability for Thursday 1st, Friday 2nd, Monday 5th, Tuesday 6th or Wednesday 7th, between 10:00am and 4:00pm."* You copy the message and run one command:

```console
$ pbpaste | whenfree --message -
Free between 10:00 and 16:00 (Europe/London), slots of 60+ minutes, 15-minute buffer around events:

- Thu 1 Oct: 12:15–16:00
- Fri 2 Oct: 10:15–13:45
- Mon 5 Oct: 10:00–14:45
- Tue 6 Oct: 10:00–14:45
- Wed 7 Oct: 10:15–12:00, 13:00–16:00

Dates and hours were read from the message by pattern matching. Check them against the message.
```

The five lines go to standard output and everything else to standard error, so `whenfree ... | pbcopy` copies exactly what you paste into your answer.

It runs on your own machine. It needs no account, no API key and no Google Cloud project, has no dependencies beyond Python, and sends nothing anywhere.

## Install

Python 3.11 or newer.

```bash
pipx install git+https://github.com/YauhenBichel/when-free      # or: uv tool install git+https://github.com/YauhenBichel/when-free
```

## Set up

```bash
whenfree init        # creates ~/.config/when-free/config.toml, readable only by you
```

Open that file and paste the **private iCal address** of your calendar into the `url` line.

| Calendar | Where the address is |
|---|---|
| Google Calendar | Settings → your calendar → Integrate calendar → **Secret address in iCal format** |
| Outlook | Settings → Calendar → Shared calendars → Publish a calendar → the ICS link |
| iCloud | Calendar → the share icon next to the calendar → Public Calendar. A `webcal://` address works as it is |
| Anything else | Any `.ics` address, or a path to an exported `.ics` file |

### Google Calendar, step by step

Do this in a browser. The phone app does not show the address.

1. Open [Google Calendar settings](https://calendar.google.com/calendar/u/0/r/settings): the gear icon, then **Settings**.
2. In the left column, under **Settings for my calendars**, click the calendar you want. The one with your own name is where invitations arrive.
3. Scroll down to **Integrate calendar** and copy **Secret address in iCal format**. It ends in `basic.ics`. Do not take "Public address in iCal format": that one only works for a calendar you have made public.
4. Paste it between the quotes of the `url` line in the settings file, so the line reads `url = "https://calendar.google.com/calendar/ical/.../basic.ics"`, and save.

Put the address in the file and nowhere else: not in a chat with an assistant, not in a shell command (`--calendar` with an address stays in your shell history), not in a repository.

Then check that it can be read:

```console
$ whenfree check
Settings: /Users/you/.config/when-free/config.toml   time zone: Europe/London
  ok  personal: 412 events, 9 block time in the next 14 days
```

Add one `[[calendar]]` block per calendar. A slot is free only if it is free in all of them.

### If it does not work

| What you see | What to do |
|---|---|
| `No calendar is configured` | The `url` line is still empty, or the file was not saved. The file is `~/.config/when-free/config.toml`, unless `WHENFREE_CONFIG` points somewhere else |
| `could not read the calendar 'personal' (...)` | The address is incomplete or is not the secret one. Copy it again with the copy button, and keep the quotes around it |
| `did not return iCalendar data; check its address` | The address is a web page, not a feed. It should end in `.ics` |
| There is no "Secret address" in Google's settings | Work and school accounts can have it switched off by the administrator. Export the calendar instead (Settings → Import & export → Export), unzip it, and use `path = "~/calendars/work.ics"`. An export is a snapshot: export again when your calendar changes |
| An event you just added is missing | The feed is refreshed with a delay. See [Limits](#limits-stated-plainly) |
| `whenfree check` is fine but a meeting does not block time | Run `whenfree --busy` to see what was read. An invitation you declined, an event marked Free and a whole-day event do not block; see [What counts as busy](#what-counts-as-busy) |

**The address is a password.** Anyone who has it can read that calendar. `whenfree` never prints it, the settings file is created with owner-only permissions, and an error names the calendar, not its address. If the address leaks, reset it in your calendar's settings.

## Use

```bash
whenfree                                              # the next 7 working days
whenfree --from 2026-10-05 --to 2026-10-09            # a range
whenfree --days "Thu 1 Oct, Fri 2 Oct, Mon 5 Oct"     # specific days
whenfree --hours 10:00-16:00 --min 90                 # only 90-minute slots, in part of the day
whenfree --message invite.txt                         # days and hours from a message saved to a file
pbpaste | whenfree --message -                        # the same, from the clipboard (macOS)
whenfree --busy                                       # also show what blocks each day
whenfree --format json                                # for scripts
whenfree --calendar ~/Downloads/calendar.ics          # one calendar, without a settings file
```

### Reading a message

`--message` reads the days and the daily window out of ordinary text by pattern matching. It understands explicit dates in the ways people write them:

`Thu 1 Oct` · `Thursday the 1st of October` · `Monday, October 5th` · `5 October` · `2026-10-05` · `Wednesday 30th`

and hours such as `between 10:00am and 4:00pm`, `10:00–16:00`, `9-5pm`, `2 to 4 pm`.

A bare "Wednesday 30th" is read as the date nearest to today that is both a Wednesday and a 30th, so a message from last week resolves to last week. Days already past are left out of the answer and named on standard error, never dropped silently.

It does not read "next week" or "any afternoon". For those, give the days yourself with `--days` or `--from` and `--to`. It always says how the dates were read, because you should check them against the message before you reply.

when-free does not connect to your mailbox. You paste the message, pipe it in, or save it to a file.

### Reading a message with your own model

If you run a language model yourself, it can do the reading instead. Add to the settings file:

```toml
[extract]
command = ["ollama", "run", "llama3.2"]          # the prompt is sent on standard input
# command = ["my-cli", "ask", "{prompt}"]        # or placed where {prompt} is
```

The command receives the message and must print JSON: `{"days": ["2026-10-05"], "hours": "10:00-16:00", "minutes": 60}`. If it fails or prints something else, pattern matching is used. Nothing runs unless you configure it, and `--no-extract` skips it for one run. The message is sent to whatever that command talks to, so use a local model for private text.

## Use it from an assistant or an agent

The same answer is available to programs in three ways. All of them read only, return the same data, and leave event titles out unless asked.

### As an MCP server

`whenfree mcp` is a Model Context Protocol server on standard input and output, with no extra install.

```bash
claude mcp add when-free -- whenfree mcp                 # Claude Code
```

For Claude Desktop, Cursor and other MCP clients, add it to their server list:

```json
{
  "mcpServers": {
    "when-free": { "command": "whenfree", "args": ["mcp"] }
  }
}
```

Then ask in ordinary words: *"Here is the recruiter's message. Which of those times can I do?"* The assistant calls `free_slots` and answers from your real calendar.

| Tool | What it does |
|---|---|
| `free_slots` | Free time ranges per day. Takes `days`, or `from` and `to`, or a `message` to read the days from; plus `hours`, `min_minutes`, `buffer_minutes`, `timezone`, `weekends`, `all_day_busy`, `include_busy` |
| `check_calendars` | Whether each calendar can be read, with event counts. No details, no addresses |

A tool that cannot do its job returns an error the assistant can read ("could not read the calendar 'work'"), never a guess.

### From a function-calling harness

If your harness registers tools from JSON schemas and runs commands, it needs two things:

```bash
whenfree schema                    # the tool definitions: name, description, inputSchema
whenfree schema --format openai    # the same, as {"type": "function", "function": {...}}
whenfree call free_slots --args '{"days": "2026-10-05, 2026-10-06", "hours": "10:00-16:00"}'
```

`whenfree call` prints one JSON object: `{"ok": true, "text": "...", "data": {...}}`, or `{"ok": false, "error": "..."}` with exit code 1. The arguments can also come on standard input.

### From Python

```python
from whenfree import api

result = api.find_free(api.Query(days="2026-10-05, 2026-10-06", hours="10:00-16:00", min_minutes=45))
for day in result["days"]:
    print(day["label"], day["free"])          # Mon 5 Oct [['10:00', '14:45']]
```

`find_free` returns plain dicts and lists, ready for `json.dumps`, and raises `api.Problem` with a message that is safe to show.

### What an agent can and cannot see

- **Free time: yes.** That is the point.
- **Event titles: only on request.** `include_busy` is off by default, and its description tells the model that titles are private.
- **Calendar addresses: never.** They are not in any tool result or error.
- **Changing anything: no.** There is no tool that writes.

## What counts as busy

| In your calendar | Blocks time? |
|---|---|
| An ordinary event | Yes, plus the buffer on both sides |
| An event marked **Free** | No |
| A cancelled event | No |
| An invitation you declined (your address in `me`) | No |
| A whole-day event | No, unless `all_day_busy = true`. Then yes, unless it is marked Free |
| A repeating event | Each occurrence, with skipped dates skipped and moved occurrences where they were moved to |

A slot shorter than `min_minutes` after the buffers are applied is not offered. For today, the day starts at the next quarter hour, not in the past.

## Settings

All optional except a calendar. Command-line flags win over the file.

| Setting | Default | Flag | Meaning |
|---|---|---|---|
| `timezone` | your system's | `--tz` | The zone the answer is given in, like `Europe/London` |
| `hours` | `09:00-18:00` | `--hours` | The part of the day you offer |
| `min_minutes` | `60` | `--min` | Shortest slot worth offering |
| `buffer_minutes` | `15` | `--buffer` | Kept free before and after every event |
| `weekends` | `false` | `--weekends` | Include Saturday and Sunday in a date range |
| `all_day_busy` | `false` | `--all-day-busy` | Whole-day events block the day |
| `days_ahead` | `7` | | Working days shown when you give no dates |
| `me` | `[]` | | Your addresses, so declined invitations do not block |
| `[[calendar]]` | | `--calendar` | `name` and `url` or `path`. Repeat the block per calendar |
| `[extract] command` | none | `--no-extract` | A command that reads a message with your own model |

Environment variables, for scripts and containers: `WHENFREE_CONFIG` (path to the settings file), `WHENFREE_CALENDARS` (comma-separated addresses or paths, replacing the file's list), `WHENFREE_TZ`.

## Limits, stated plainly

- **It reads; it does not book.** It never writes to a calendar and never sends a message.
- **It is as fresh as the feed.** Google refreshes the secret iCal address with some delay, so an event added a minute ago may not be there yet. Run `whenfree --busy` to see what it saw.
- **Recurrence rules.** Daily, weekly, monthly (by date, or "first Monday", "last Friday") and yearly rules are expanded, with intervals, end dates, counts, skipped dates and moved occurrences. Rarer rules (`BYSETPOS`, week numbers) are not. For those the first date is blocked and a note says so. Nothing is guessed.
- **Every calendar or none.** If one calendar cannot be read, no slots are printed, because busy time would look free.
- **Time zones** come from the events. A zone name the tz database does not know (some Outlook exports) is read in your own zone.

## Development

```bash
uv run --with pytest pytest -q        # under a second; no network
```

The tests use a small calendar in `tests/data/sample.ics` and a fixed clock (`WHENFREE_NOW`). See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

Apache-2.0.
