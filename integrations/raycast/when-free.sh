#!/bin/bash

# Raycast script command: when am I free?
#
# @raycast.schemaVersion 1
# @raycast.title When am I free
# @raycast.mode fullOutput
# @raycast.packageName when-free
# @raycast.icon 📅
# @raycast.argument1 { "type": "text", "placeholder": "days: next week, tomorrow, Thu 15 Oct", "optional": true }
# @raycast.argument2 { "type": "text", "placeholder": "hours: afternoon, 10:00-16:00", "optional": true }
# @raycast.description Your free slots, from your calendars. Copies them to the clipboard.

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
args=()
[ -n "$1" ] && args+=(--days "$1")
[ -n "$2" ] && args+=(--hours "$2")
whenfree "${args[@]}" | tee >(pbcopy)
