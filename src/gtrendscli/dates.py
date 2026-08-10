"""Date parsing and calendar-period clamping.

The API takes ``YYYY-MM-DD`` on one endpoint and ``YYYY-MM`` on the rest, and
coarse intervals return fixed calendar periods that the requested dates merely
overlap. Both problems are handled here so no caller ever sees them.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Literal

# `date.weekday()` numbering: Monday is 0, Sunday is 6.
SUNDAY = 6

Bound = Literal["start", "end"]


class DateFormatError(ValueError):
    """A date string could not be parsed, or a range ran backwards."""


class ClampError(ValueError):
    """The requested range contains no whole period at the chosen interval."""


class Interval(StrEnum):
    """Calendar period size the API buckets values into."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


@dataclass(frozen=True)
class DateRange:
    """An inclusive span of dates, as the user asked for it."""

    start: date
    end: date


@dataclass(frozen=True)
class Period:
    """One whole calendar period the API will actually return a value for."""

    start: date
    end: date


@dataclass(frozen=True)
class ClampResult:
    """Whole periods inside a requested range, plus the partials trimmed off."""

    periods: list[Period]
    dropped_start: DateRange | None = None
    dropped_end: DateRange | None = None


_YEAR = re.compile(r"^(\d{4})$")
_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_MONTH_DAY = re.compile(r"^(\d{2})-(\d{2})$")
_YEAR_SPAN = re.compile(r"^(\d{4})-(\d{4})$")


def parse_calendar_window(
    from_text: str, to_text: str | None, *, year: int
) -> DateRange:
    """Resolve a ``MM-DD`` window inside a given year.

    Comparing the same calendar dates across years needs bounds without a year
    of their own, which is the one place a non-ISO date shape is unavoidable.
    """
    bounds = []
    for text in (from_text, to_text or from_text):
        match = _MONTH_DAY.match(text)
        if not match:
            raise DateFormatError(
                f"expected MM-DD when comparing years, got {text!r}"
            )
        month, day = int(match.group(1)), int(match.group(2))
        try:
            bounds.append(date(year, month, day))
        except ValueError as exc:
            raise DateFormatError(
                f"{text!r} is not a real date in {year}"
            ) from exc

    if bounds[1] < bounds[0]:
        raise DateFormatError(
            f"window ends before it starts: {from_text}..{to_text}"
        )

    return DateRange(bounds[0], bounds[1])


def parse_years(text: str) -> list[int]:
    """Parse ``2021-2026`` or ``2021,2023,2026`` into a list of years."""
    if match := _YEAR_SPAN.match(text):
        first, last = int(match.group(1)), int(match.group(2))
        if last < first:
            raise DateFormatError(f"year range runs backwards: {text!r}")
        return list(range(first, last + 1))

    years = []
    for part in text.split(","):
        if not _YEAR.match(part.strip()):
            raise DateFormatError(
                f"cannot parse years {text!r}; expected 2021-2026 or 2021,2023"
            )
        years.append(int(part.strip()))

    return years


def _last_day_of_month(year: int, month: int) -> int:
    try:
        return calendar.monthrange(year, month)[1]
    except calendar.IllegalMonthError as exc:
        raise DateFormatError(
            f"month out of range: {year}-{month:02d}"
        ) from exc


def _period_named_by(text: str) -> tuple[date, date]:
    """Return the first and last day of the period a date string names.

    ``2026`` names a year, ``2026-07`` a month, ``2026-07-21`` a single day.
    """
    # A bare year covers January through December.
    if match := _YEAR.match(text):
        year = int(match.group(1))
        try:
            return date(year, 1, 1), date(year, 12, 31)
        except ValueError as exc:
            raise DateFormatError(f"year out of range: {text}") from exc

    # A year-month covers the whole month, leap years included.
    if match := _MONTH.match(text):
        year, month = int(match.group(1)), int(match.group(2))
        last = _last_day_of_month(year, month)
        try:
            return date(year, month, 1), date(year, month, last)
        except ValueError as exc:
            raise DateFormatError(f"year out of range: {text}") from exc

    # A full date names itself.
    if match := _DAY.match(text):
        try:
            day = date(*(int(part) for part in match.groups()))
        except ValueError as exc:
            raise DateFormatError(f"not a real date: {text!r}") from exc
        return day, day

    raise DateFormatError(
        f"cannot parse date {text!r}; expected YYYY, YYYY-MM or YYYY-MM-DD "
        "with zero-padded parts"
    )


def today_utc() -> date:
    """Today in UTC, which is how the API bins its days.

    Local time would be wrong by a day for much of the world: from a US Pacific
    machine, `date.today()` still reads yesterday while the API is already
    serving the current UTC day, so a defaulted `--to` would silently drop the
    newest point.
    """
    return datetime.now(UTC).date()


def parse_bound(text: str, *, bound: Bound) -> date:
    """Parse one end of a range, expanding partial dates outward."""
    first, last = _period_named_by(text)
    return first if bound == "start" else last


def parse_range(
    from_text: str, to_text: str | None, *, today: date
) -> DateRange:
    """Assemble an inclusive range from the user's ``--from`` and ``--to``.

    When ``--to`` is omitted the default depends on how specific ``--from`` was:
    a partial date names a period and means exactly that period (``--from
    2026-07`` is July), while a full date means everything since (``--from
    2026-07-21`` runs to today).
    """
    first, last = _period_named_by(from_text)

    if to_text is not None:
        end = parse_bound(to_text, bound="end")
    elif last > first:
        end = last
    else:
        end = today

    if end < first:
        raise DateFormatError(f"range ends before it starts: {first} to {end}")

    return DateRange(first, end)


def period_end(start: date, interval: Interval) -> date:
    """Return the last day of the period beginning on ``start``.

    Responses label a period by its first day only, so the coverage each value
    describes has to be reconstructed before it can be recorded.
    """
    if interval is Interval.DAY:
        return start
    if interval is Interval.WEEK:
        return start + timedelta(days=6)
    if interval is Interval.YEAR:
        return date(start.year, 12, 31)
    return date(
        start.year, start.month, _last_day_of_month(start.year, start.month)
    )


def _days(span: DateRange) -> Iterator[Period]:
    day = span.start
    while day <= span.end:
        yield Period(day, day)
        day += timedelta(days=1)


def _weeks(span: DateRange, week_start: int) -> Iterator[Period]:
    # Skip forward to the first week boundary at or after the range start.
    start = span.start + timedelta(days=(week_start - span.start.weekday()) % 7)

    while start + timedelta(days=6) <= span.end:
        yield Period(start, start + timedelta(days=6))
        start += timedelta(days=7)


def _months(span: DateRange) -> Iterator[Period]:
    year, month = span.start.year, span.start.month

    while (first := date(year, month, 1)) <= span.end:
        # Only months fully inside the range survive; partials are dropped.
        last = date(year, month, _last_day_of_month(year, month))
        if first >= span.start and last <= span.end:
            yield Period(first, last)

        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _calendar_years(span: DateRange) -> Iterator[Period]:
    year = span.start.year

    while (first := date(year, 1, 1)) <= span.end:
        last = date(year, 12, 31)
        if first >= span.start and last <= span.end:
            yield Period(first, last)
        year += 1


def clamp(
    span: DateRange, interval: Interval, *, week_start: int = SUNDAY
) -> ClampResult:
    """Reduce a requested range to the whole calendar periods inside it.

    Silently widening a short request to a whole period could include the very
    event the caller meant to exclude, so a range with no whole period is an
    error rather than a best effort.

    ``week_start`` defaults to Sunday, which the live suite confirms against the
    API rather than assuming.
    """
    builders = {
        Interval.DAY: lambda: _days(span),
        Interval.WEEK: lambda: _weeks(span, week_start),
        Interval.MONTH: lambda: _months(span),
        Interval.YEAR: lambda: _calendar_years(span),
    }
    periods = list(builders[interval]())

    if not periods:
        raise ClampError(
            f"{span.start}..{span.end} contains no whole {interval.value}; "
            f"widen the range or use a finer --interval"
        )

    # Report the partial periods trimmed off each end so coverage stays visible.
    dropped_start = (
        DateRange(span.start, periods[0].start - timedelta(days=1))
        if periods[0].start > span.start
        else None
    )
    dropped_end = (
        DateRange(periods[-1].end + timedelta(days=1), span.end)
        if periods[-1].end < span.end
        else None
    )

    return ClampResult(periods, dropped_start, dropped_end)
