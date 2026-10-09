"""Tests for time points and validity intervals."""

from datetime import date, datetime, timezone

import pytest

from chickentruck._temporal import TimePoint, contains, overlaps, parse_time


@pytest.mark.parametrize(
    "text, precision, iso",
    [
        ("1706", "year", "1706"),
        ("1706-01", "month", "1706-01"),
        ("1706-01-17", "day", "1706-01-17"),
        ("2026-10-09T12:30:00Z", "instant", "2026-10-09T12:30:00+00:00"),
    ],
)
def test_parse_time_keeps_precision(text, precision, iso):
    point = parse_time(text)

    assert point.precision == precision
    assert point.isoformat() == iso


def test_parse_time_accepts_python_values():
    assert parse_time(1706).precision == "year"
    assert parse_time(date(1706, 1, 17)).precision == "day"
    assert parse_time(datetime(2026, 1, 1, tzinfo=timezone.utc)).precision == "instant"
    assert parse_time(None) is None


def test_parse_time_rejects_garbage():
    with pytest.raises(ValueError):
        parse_time("last tuesday")
    with pytest.raises(TypeError):
        parse_time(True)


def test_naive_instant_is_flagged_and_cannot_be_placed():
    point = parse_time("2026-10-09T12:30:00")

    assert point.is_naive
    with pytest.raises(ValueError):
        point.earliest()


def test_precision_must_match_value_type():
    with pytest.raises(ValueError):
        TimePoint(date(2026, 1, 1), "instant")
    with pytest.raises(ValueError):
        TimePoint(datetime(2026, 1, 1, tzinfo=timezone.utc), "day")


def test_contains_is_half_open():
    start, end = parse_time("1757"), parse_time("1775")

    assert contains(start, end, parse_time("1757"))
    assert contains(start, end, parse_time("1774-12-31"))
    assert not contains(start, end, parse_time("1775"))
    assert contains(None, None, parse_time("1000"))


def test_overlaps_treats_none_as_unbounded():
    assert overlaps(parse_time("1700"), parse_time("1750"), parse_time("1749"), None)
    assert not overlaps(parse_time("1700"), parse_time("1750"), parse_time("1750"), None)
    assert overlaps(None, None, parse_time("1750"), parse_time("1760"))
