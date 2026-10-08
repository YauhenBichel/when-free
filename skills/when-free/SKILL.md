---
name: when-free
description: Answer "when am I free?" from the user's own calendars. Use when the user asks about their availability, wants times to offer someone, pastes a message asking when they can meet, or asks whether they are free now. Uses the when-free MCP tools; read-only.
---

# when-free

when-free reads the user's calendars on their own machine and says which times are
free. It only reads: it cannot create, change or delete anything.

## When to use it

- "When am I free next week?", "any afternoon on Thursday?"
- The user pastes a message such as "Could we meet Tuesday or Wednesday?" and wants
  times to offer.
- "Am I free right now?" or "until when am I busy?"
- Before proposing or confirming any meeting time on the user's behalf.

## How

1. **Free times for a period or a pasted message:** call `free_slots`. Pass the
   user's words, or the pasted message, as they are; it understands explicit dates
   and phrases like "next week" or "any afternoon".
2. **Right now:** call `status`.
3. **Something looks wrong** (no slots at all, or an error about calendars): call
   `check_calendars` and tell the user what it reports.

Answer with the slots it returns. Never invent times, and never offer a time the tool
did not return.

## Privacy

- Do not mention event titles or who the user meets unless the user asks.
- If the user wants to share their availability with someone, give the slots only.

## If no calendar is set up

The tools will say so. Tell the user, in plain words, to run this once in a terminal
and paste their calendar's private `.ics` address when asked:

```
uvx when-free add
```

The address works like a password. Ask them to give it to `when-free add` only, and
never to paste it into the chat.
