---
name: when-free
description: Answer "when am I free?" from the user's own calendars. Use when the user asks about their availability, wants times to offer someone, pastes a message asking when they can meet, or asks whether they are free now. Uses the when-free MCP tools; read-only.
---

# when-free

when-free finds the time slots the user can offer. It collects the request with
tools, reads the calendars with `free_slots`, and hands the slots back with tools.
It cannot create, change or delete calendar events.

## When to use it

- "When am I free next week?", "any afternoon on Thursday?"
- The user pastes a message such as "Could we meet Tuesday or Wednesday?" and wants
  times to offer.
- "Am I free right now?" or "until when am I busy?"
- Before proposing or confirming any meeting time on the user's behalf.

## How

1. **Collect the request.** If it is already in the chat, use that text. If it is in
   mail or chat, read it with the matching tool (`gmail_read`, `outlook_read`,
   `slack_history`, `teams_history`) and take the dates and hours from what that
   tool returns. Do not look for a calendar there.
2. **Free times:** call `free_slots`. Pass the collected text as `message`, a phrase
   such as "next week" in `days`, and dates in `from` and `to` (YYYY-MM-DD). It
   understands explicit dates and phrases like "next week" or "any afternoon". Set
   `min_minutes` to the meeting length when the user gives one.
3. **Right now:** call `status`.
4. **Hand the slots back** with the slots `free_slots` returned. A mail reply is
   `gmail_draft` or `outlook_draft` (a draft, not a sent message). Post to Slack or
   Teams only when the user asked to post.
5. **Something looks wrong** (no slots at all, or an error about calendars): call
   `check_calendars` and tell the user what it reports.

Answer with the slots it returns. Never invent times, and never offer a time the tool
did not return.

## How to answer

- Keep it short: one line per day, the times on that line, and the time zone once.
- If there are many slots, give the best few and say there are more.
- If the user pasted a message from someone, end with a ready-to-send reply in the
  same language and tone, offering two or three of the slots. For example:
  "Thanks! I could do Tuesday 10:00–11:30 or Wednesday after 14:00 (London time)."
- If nothing is free, say so kindly and offer to look at the following days.

## Privacy

- Do not mention event titles or who the user meets unless the user asks.
- If the user wants to share their availability with someone, give the slots only.

## If no calendar is set up

The tools will say so. Stop there: do not look for the user's calendar in other tools
or connectors instead. Tell the user, in plain words, to run this once in a terminal
and paste their calendar's private `.ics` address when asked:

```
uvx when-free add
```

It explains where to find the address in Google Calendar, Outlook and iCloud, checks
it, and saves it. Then ask your question again.

The address works like a password. Ask them to give it to `when-free add` only, and
never to paste it into the chat.
