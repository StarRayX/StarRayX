from __future__ import annotations

from datetime import date, datetime

import pytest

from phhack.dates import parse_any, parse_epoch, parse_iso, parse_range


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Jan 08 - Mar 15, 2026", (date(2026, 1, 8), date(2026, 3, 15))),
        ("Dec 20, 2025 - Jan 10, 2026", (date(2025, 12, 20), date(2026, 1, 10))),
        ("Sep 5 - Sep 7, 2026", (date(2026, 9, 5), date(2026, 9, 7))),
        ("March 1 - April 30, 2026", (date(2026, 3, 1), date(2026, 4, 30))),
        ("Mar 15, 2026", (date(2026, 3, 15), None)),
        ("", (None, None)),
        (None, (None, None)),
        ("no dates here", (None, None)),
    ],
)
def test_parse_range(text, expected):
    assert parse_range(text) == expected


def test_range_rolls_the_start_year_back_when_it_would_follow_the_end():
    """Devpost prints the year once. "Nov 01 - Feb 28, 2026" spans a new year."""
    assert parse_range("Nov 01 - Feb 28, 2026") == (date(2025, 11, 1), date(2026, 2, 28))


def test_invalid_calendar_dates_are_rejected():
    assert parse_range("Feb 30, 2026") == (None, None)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-03-15", date(2026, 3, 15)),
        ("2026-03-15T10:00:00Z", date(2026, 3, 15)),
        ("2026-03-15T10:00:00+08:00", date(2026, 3, 15)),
        ("2026/03/15", date(2026, 3, 15)),
        ("", None),
        (None, None),
        ("garbage", None),
    ],
)
def test_parse_iso(value, expected):
    assert parse_iso(value) == expected


def test_parse_epoch_handles_seconds_and_milliseconds():
    assert parse_epoch(1774000000) == parse_epoch(1774000000000)
    assert parse_epoch(0) is None
    assert parse_epoch("nope") is None


def test_parse_any_accepts_every_shape_sources_emit():
    assert parse_any(date(2026, 1, 1)) == date(2026, 1, 1)
    assert parse_any(datetime(2026, 1, 1, 12)) == date(2026, 1, 1)
    assert parse_any("2026-01-01") == date(2026, 1, 1)
    assert parse_any(1774000000) is not None
    assert parse_any("1774000000") is not None
    assert parse_any({"unexpected": "dict"}) is None
    assert parse_any(None) is None
