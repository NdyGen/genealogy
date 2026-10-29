"""Reads a Claude Code usage-limit message from screen text and returns when the limit resets."""

from __future__ import annotations

import datetime as dt
import re

MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}
# Only a reached limit; "You've used 76% of your weekly limit · resets ..." is a warning on the same line style.
LIMIT = re.compile(
    r"(?:hit your [\w -]*limit|limit reached)[^\n]{0,80}?reset(?:s| at)\s+(?:([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+)?"
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)",
    re.I,
)
# An account without Claude Code access answers every request with this; no reset time is given, so the
# account counts as full for a day and is then tried again.
_BLOCKED = re.compile(r"disabled Claude subscription access|ask your admin to enable access", re.I)
BLOCKED_HOURS = 24
# Claude closes each turn with "· done 9:43 PM"; the one after the limit message dates that message.
_DONE_AT = re.compile(r"done (\d{1,2}):(\d{2}) ?(AM|PM)", re.I)


def _hour24(hour: str, ampm: str) -> int:
    return int(hour) % 12 + (12 if ampm.lower() == "pm" else 0)


def limit_reset(screen: str, now: dt.datetime) -> int | None:
    """Epoch of the reset announced by the last usage-limit message on the screen, in local time.

    A reset without a date is the first such time after the message appeared, not after now: a leader
    can sit on yesterday evening's "resets 12:30am" until the next morning.
    """
    hits = list(LIMIT.finditer(screen))
    if not hits:
        if _BLOCKED.search(screen):
            return int((now + dt.timedelta(hours=BLOCKED_HOURS)).timestamp())
        return None
    last = hits[-1]
    month, day, hour, minute, ampm = last.groups()
    if month and month.lower()[:3] in MONTHS:
        reset = dt.datetime(now.year, MONTHS[month.lower()[:3]], int(day), _hour24(hour, ampm), int(minute or 0))
        if reset < now - dt.timedelta(days=180):
            reset = reset.replace(year=now.year + 1)
        return int(reset.timestamp())
    moment = now
    dated = _DONE_AT.search(screen, last.end())
    if dated:
        moment = now.replace(hour=_hour24(dated[1], dated[3]), minute=int(dated[2]), second=0,
                             microsecond=0)
        if moment > now:
            moment -= dt.timedelta(days=1)
    reset = moment.replace(hour=_hour24(hour, ampm), minute=int(minute or 0), second=0, microsecond=0)
    if reset <= moment:
        reset += dt.timedelta(days=1)
    return int(reset.timestamp())
