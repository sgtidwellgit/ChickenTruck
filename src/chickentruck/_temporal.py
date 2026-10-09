"""Temporal values for knowledge: points with precision, and validity intervals.

A `TimePoint` keeps the precision it was stated with, so "1706" stays a
year rather than being faked into 1706-01-01. Validity is the half-open
interval ``[valid_from, valid_to)``; ``None`` on either side means
unbounded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional, Union

YEAR = "year"
MONTH = "month"
DAY = "day"
INSTANT = "instant"

PRECISIONS = (YEAR, MONTH, DAY, INSTANT)

_YEAR_RE = re.compile(r"^(\d{4})$")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_DAY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


@dataclass(frozen=True)
class TimePoint:
    """A point in time and the precision it is known to.

    ``value`` is a ``date`` for year/month/day precision and a ``datetime``
    for instant precision. A naive ``datetime`` is allowed here but fails
    validation in `grill` -- instants must carry a timezone.
    """

    value: Union[date, datetime]
    precision: str = DAY

    def __post_init__(self) -> None:
        if self.precision not in PRECISIONS:
            raise ValueError(f"unknown precision {self.precision!r}")
        if self.precision == INSTANT and not isinstance(self.value, datetime):
            raise ValueError("instant precision requires a datetime value")
        if self.precision != INSTANT and isinstance(self.value, datetime):
            raise ValueError(f"{self.precision} precision requires a date value")

    @property
    def is_naive(self) -> bool:
        """True when this is an instant without timezone information."""

        return isinstance(self.value, datetime) and self.value.tzinfo is None

    def earliest(self) -> datetime:
        """The first instant this point covers, as an aware UTC datetime.

        Raises ``ValueError`` for a naive instant, since it has no defined
        position on the timeline.
        """

        if isinstance(self.value, datetime):
            if self.value.tzinfo is None:
                raise ValueError("cannot place a naive datetime on the timeline")
            return self.value.astimezone(timezone.utc)
        return datetime(
            self.value.year, self.value.month, self.value.day, tzinfo=timezone.utc
        )

    def isoformat(self) -> str:
        """ISO-8601 text at this point's precision (e.g. ``"1706"``)."""

        if self.precision == YEAR:
            return f"{self.value.year:04d}"
        if self.precision == MONTH:
            return f"{self.value.year:04d}-{self.value.month:02d}"
        return self.value.isoformat()

    def __str__(self) -> str:
        return self.isoformat()


TimeLike = Union[TimePoint, datetime, date, int, str]


def parse_time(value: Optional[TimeLike]) -> Optional[TimePoint]:
    """Convert a date, datetime, year, or ISO-8601 string into a `TimePoint`.

    Accepted strings: ``"YYYY"``, ``"YYYY-MM"``, ``"YYYY-MM-DD"``, and full
    ISO datetimes (a trailing ``"Z"`` is read as UTC). ``None`` passes
    through unchanged.
    """

    if value is None or isinstance(value, TimePoint):
        return value
    if isinstance(value, datetime):
        return TimePoint(value, INSTANT)
    if isinstance(value, date):
        return TimePoint(value, DAY)
    if isinstance(value, bool):
        raise TypeError("cannot interpret a bool as a time")
    if isinstance(value, int):
        return TimePoint(date(value, 1, 1), YEAR)
    if isinstance(value, str):
        text = value.strip()
        match = _YEAR_RE.match(text)
        if match:
            return TimePoint(date(int(match.group(1)), 1, 1), YEAR)
        match = _MONTH_RE.match(text)
        if match:
            return TimePoint(date(int(match.group(1)), int(match.group(2)), 1), MONTH)
        match = _DAY_RE.match(text)
        if match:
            return TimePoint(date.fromisoformat(text), DAY)
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            return TimePoint(datetime.fromisoformat(text), INSTANT)
        except ValueError:
            raise ValueError(f"unrecognized time value {value!r}") from None
    raise TypeError(f"cannot interpret {type(value).__name__} as a time")


def contains(
    valid_from: Optional[TimePoint], valid_to: Optional[TimePoint], at: TimePoint
) -> bool:
    """True when ``at`` falls inside ``[valid_from, valid_to)``."""

    moment = at.earliest()
    if valid_from is not None and moment < valid_from.earliest():
        return False
    if valid_to is not None and moment >= valid_to.earliest():
        return False
    return True


def overlaps(
    a_from: Optional[TimePoint],
    a_to: Optional[TimePoint],
    b_from: Optional[TimePoint],
    b_to: Optional[TimePoint],
) -> bool:
    """True when two half-open validity intervals share any instant."""

    if a_to is not None and b_from is not None and a_to.earliest() <= b_from.earliest():
        return False
    if b_to is not None and a_from is not None and b_to.earliest() <= a_from.earliest():
        return False
    return True
