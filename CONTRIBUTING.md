# Contributing

Thanks for looking. Issues and pull requests are both welcome.

## The most useful contribution

**A calendar that is read wrongly.** If `whenfree --busy` shows an event at the wrong time, misses one,
or blocks a day it should not, please open an issue with the smallest `.ics` snippet that shows it:
one `VEVENT`, with titles and addresses replaced. Recurrence rules and time zones from Outlook and
iCloud exports are the most likely places.

Ways of writing a date or a time range that `--message` does not read are just as welcome. Paste the
sentence and say what you expected.

## Working on the code

```bash
uv run --with pytest pytest -q        # under a second; no network
```

Please keep to the shape of what is there:

- **No dependencies.** The standard library has been enough so far.
- **A test for the behaviour you change.** Calendar cases go in `tests/data/sample.ics` with a line in
  `tests/test_slots.py` saying what the day should look like.
- **Never guess availability.** When something cannot be read, say so and block the time or stop.
  Offering a slot that is actually busy is the one failure this tool must not have.
- **Never print a calendar address**, in output, errors or logs. It is a password.
