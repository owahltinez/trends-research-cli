"""Date parsing and the clamp rule.

These are the highest-value tests in the project: nearly every wrong published
number traced back to a date bug, and none of this needs the network.
"""

from datetime import date

import pytest

from trends_research_cli.dates import (
    ClampError,
    DateFormatError,
    DateRange,
    Interval,
    clamp,
    parse_bound,
    parse_range,
)

TODAY = date(2026, 8, 10)


# --- partial dates expand outward -------------------------------------------


@pytest.mark.parametrize(
    ("text", "bound", "expected"),
    [
        ("2026", "start", date(2026, 1, 1)),
        ("2026", "end", date(2026, 12, 31)),
        ("2026-07", "start", date(2026, 7, 1)),
        ("2026-07", "end", date(2026, 7, 31)),
        ("2026-02", "end", date(2026, 2, 28)),
        ("2024-02", "end", date(2024, 2, 29)),
        ("2026-07-21", "start", date(2026, 7, 21)),
        ("2026-07-21", "end", date(2026, 7, 21)),
    ],
)
def test_parse_bound_expands_partial_dates(text, bound, expected):
    assert parse_bound(text, bound=bound) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "26-07",
        "2026-13",
        "2026-07-32",
        "2026-00",
        "july",
        "2026-7",
        "2026/07/21",
    ],
)
def test_parse_bound_rejects_malformed(text):
    with pytest.raises(DateFormatError):
        parse_bound(text, bound="start")


# --- range assembly ---------------------------------------------------------


def test_partial_from_without_to_covers_that_period():
    """`--from 2026-07` means July, not July-onwards (acceptance test 5)."""
    assert parse_range("2026-07", None, today=TODAY) == DateRange(
        date(2026, 7, 1), date(2026, 7, 31)
    )


def test_bare_year_without_to_covers_that_year():
    assert parse_range("2026", None, today=TODAY) == DateRange(
        date(2026, 1, 1), date(2026, 12, 31)
    )


def test_full_from_without_to_runs_to_today():
    assert parse_range("2026-07-21", None, today=TODAY) == DateRange(
        date(2026, 7, 21), TODAY
    )


def test_explicit_to_wins_over_partial_from():
    assert parse_range("2026-07", "2026-09", today=TODAY) == DateRange(
        date(2026, 7, 1), date(2026, 9, 30)
    )


def test_reversed_range_is_rejected():
    with pytest.raises(DateFormatError):
        parse_range("2026-09", "2026-07", today=TODAY)


# --- the clamp rule ---------------------------------------------------------


def test_daily_interval_never_drops_anything():
    result = clamp(
        DateRange(date(2026, 7, 21), date(2026, 7, 26)), Interval.DAY
    )

    assert len(result.periods) == 6
    assert all(p.start == p.end for p in result.periods)
    assert result.dropped_start is None and result.dropped_end is None


def test_month_interval_keeps_only_whole_months_and_reports_drops():
    """Acceptance test 3: Jul 15 - Sep 20 at month interval is August only."""
    result = clamp(
        DateRange(date(2026, 7, 15), date(2026, 9, 20)), Interval.MONTH
    )

    assert [(p.start, p.end) for p in result.periods] == [
        (date(2026, 8, 1), date(2026, 8, 31))
    ]
    assert result.dropped_start == DateRange(
        date(2026, 7, 15), date(2026, 7, 31)
    )
    assert result.dropped_end == DateRange(date(2026, 9, 1), date(2026, 9, 20))


def test_month_interval_over_short_range_errors():
    """Acceptance test 2: widening to a whole month is the worst failure."""
    with pytest.raises(ClampError, match="no whole month"):
        clamp(DateRange(date(2026, 7, 21), date(2026, 7, 26)), Interval.MONTH)


def test_exact_month_boundaries_drop_nothing():
    result = clamp(
        DateRange(date(2026, 7, 1), date(2026, 9, 30)), Interval.MONTH
    )

    assert len(result.periods) == 3
    assert result.dropped_start is None and result.dropped_end is None


def test_week_periods_align_to_week_start_and_stay_inside_range():
    rng = DateRange(date(2026, 7, 1), date(2026, 8, 31))
    result = clamp(
        rng, Interval.WEEK, week_start=6
    )  # Sunday, per date.weekday()

    assert result.periods, "a two-month range contains whole weeks"
    for period in result.periods:
        assert period.start.weekday() == 6
        assert (period.end - period.start).days == 6
        assert rng.start <= period.start and period.end <= rng.end


def test_week_interval_over_short_range_errors():
    with pytest.raises(ClampError, match="no whole week"):
        clamp(DateRange(date(2026, 7, 21), date(2026, 7, 24)), Interval.WEEK)


def test_year_interval_keeps_only_whole_calendar_years():
    result = clamp(DateRange(date(2022, 6, 1), date(2025, 3, 1)), Interval.YEAR)

    assert [(p.start, p.end) for p in result.periods] == [
        (date(2023, 1, 1), date(2023, 12, 31)),
        (date(2024, 1, 1), date(2024, 12, 31)),
    ]
    assert result.dropped_start == DateRange(
        date(2022, 6, 1), date(2022, 12, 31)
    )
    assert result.dropped_end == DateRange(date(2025, 1, 1), date(2025, 3, 1))


def test_year_interval_over_a_partial_year_errors():
    with pytest.raises(ClampError, match="no whole year"):
        clamp(DateRange(date(2025, 2, 1), date(2025, 11, 1)), Interval.YEAR)
