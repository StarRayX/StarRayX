"""Date parsing for the many formats hackathon sites emit."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Optional, Tuple

_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

# "Jan 08" / "Jan 08, 2026" / "January 8 2026"
_DATE_PART_RE = re.compile(
    r"(?P<month>[A-Za-z]{3,9})\.?\s+(?P<day>\d{1,2})(?:\s*,?\s*(?P<year>\d{4}))?"
)


def parse_iso(value: Optional[str]) -> Optional[date]:
    """Parse ISO-8601 dates and datetimes, tolerating a trailing 'Z'."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_epoch(value) -> Optional[date]:
    """Parse a UNIX timestamp in seconds or milliseconds."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    if number > 1e11:  # milliseconds
        number /= 1000.0
    try:
        return datetime.fromtimestamp(number, tz=timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None


def parse_any(value) -> Optional[date]:
    """Best-effort single-date parse across the formats sources actually use."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        return parse_epoch(value)
    if not isinstance(value, str):
        return None

    parsed = parse_iso(value)
    if parsed:
        return parsed
    if value.strip().isdigit():
        return parse_epoch(value.strip())

    match = _DATE_PART_RE.search(value)
    if match:
        return _build(match, fallback_year=None)
    return None


def parse_range(text: Optional[str]) -> Tuple[Optional[date], Optional[date]]:
    """Parse Devpost-style ranges such as ``"Jan 08 - Mar 15, 2026"``.

    The year is often printed only once, at the end, so a leading part with no
    year inherits it — and rolls back a year when that would put the start
    after the end (a December-to-January event).
    """
    if not text or not isinstance(text, str):
        return None, None

    matches = list(_DATE_PART_RE.finditer(text))
    if not matches:
        return None, None

    trailing_year: Optional[int] = None
    for match in reversed(matches):
        if match.group("year"):
            trailing_year = int(match.group("year"))
            break

    if len(matches) == 1:
        return _build(matches[0], trailing_year), None

    start = _build(matches[0], trailing_year)
    end = _build(matches[-1], trailing_year)
    if start and end and start > end:
        start = start.replace(year=start.year - 1)
    return start, end


def _build(match: "re.Match[str]", fallback_year: Optional[int]) -> Optional[date]:
    month = _MONTHS.get(match.group("month").lower().rstrip("."))
    if not month:
        return None
    day = int(match.group("day"))
    year = int(match.group("year")) if match.group("year") else fallback_year
    if year is None:
        year = date.today().year
    try:
        return date(year, month, day)
    except ValueError:
        return None
