#!/bin/bash
# macOS menu bar: SwiftBar (https://swiftbar.app) or xbar (https://xbarapp.com). Also GNOME Shell with Argos.
# Shows "🔴 busy → 15:30" or "🟢 free → 14:00"; the menu has today's free slots and the next one.
# The ".1m." in the file name makes it refresh every minute. Calendars are fetched at most every 5 minutes.
#
# <xbar.title>when-free</xbar.title>
# <xbar.desc>Free or busy now, from your own calendars.</xbar.desc>
# <xbar.dependencies>when-free</xbar.dependencies>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>false</swiftbar.hideLastUpdated>

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
whenfree now --format xbar
