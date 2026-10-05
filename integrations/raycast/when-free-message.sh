#!/bin/bash

# Raycast script command: answer the availability message on the clipboard.
#
# @raycast.schemaVersion 1
# @raycast.title When am I free for this message
# @raycast.mode fullOutput
# @raycast.packageName when-free
# @raycast.icon 📅
# @raycast.description Copy the message asking for your availability, then run this. The slots replace it on the clipboard.

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
pbpaste | whenfree --message - | tee >(pbcopy)
