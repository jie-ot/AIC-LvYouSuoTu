"""Clock helpers for itinerary schedules.

``start_time`` / ``end_time`` are same-day ``HH:MM`` strings. When the end
clock is earlier than the start clock, the segment is an overnight leg and
the end belongs to the next calendar day. The trip date range does not have
to include that arrival date.
"""

from __future__ import annotations

import re

_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
_MINUTES_PER_DAY = 24 * 60


def parse_clock_minutes(value: str | None) -> int | None:
    if not value or not _TIME_RE.match(value):
        return None
    hh, mm = (int(x) for x in value.split(":"))
    if hh > 23 or mm > 59:
        return None
    return hh * 60 + mm


def timeline_end_minutes(start_m: int | None, end_m: int | None) -> int | None:
    """Minutes from midnight of the start day, wrapping overnight ends by 24h."""
    if end_m is None:
        return None
    if start_m is not None and end_m < start_m:
        return end_m + _MINUTES_PER_DAY
    return end_m


def is_overnight(start_time: str | None, end_time: str | None) -> bool:
    start_m = parse_clock_minutes(start_time)
    end_m = parse_clock_minutes(end_time)
    return start_m is not None and end_m is not None and end_m < start_m


def format_time_range(start_time: str | None, end_time: str | None) -> str | None:
    if start_time and end_time:
        if is_overnight(start_time, end_time):
            return f"{start_time}-次日{end_time}"
        return f"{start_time}-{end_time}"
    if start_time:
        return start_time
    return None
