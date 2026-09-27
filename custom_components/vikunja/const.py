"""Constants for the Vikunja integration."""

from datetime import timedelta

DOMAIN = "vikunja"

DEFAULT_URL = "http://localhost:3456"

# Completed tasks stay visible in the to-do lists for this long.
RECENTLY_DONE = "now-7d"

# How long a task with only a due date lasts on the calendar.
DUE_EVENT_LENGTH = timedelta(minutes=30)

SCAN_INTERVAL = timedelta(minutes=1)
