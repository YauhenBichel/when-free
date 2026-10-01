# Security

## Reporting

Please report a vulnerability through GitHub's private advisory form on this repository
("Security" → "Report a vulnerability"), not in a public issue. I aim to reply within a week.

## What this tool does with your data

- It downloads the calendar feeds **you** configured, over HTTPS, and reads them in memory. It does
  not write to any calendar and stores nothing on disk.
- A private iCal address is a password for that calendar. The settings file is created with
  owner-only permissions (`0600`). The address is never printed: errors name the calendar instead.
- `--message` reads text you give it. Nothing connects to a mailbox.
- The optional `[extract]` command runs only if you configure it, and sends the message to whatever
  that command talks to. Use a model you run yourself for private text.
- Nothing else is sent anywhere. There is no telemetry.

If an address leaks, reset it in the calendar's own settings (Google Calendar: Settings → your
calendar → Integrate calendar → Reset).
