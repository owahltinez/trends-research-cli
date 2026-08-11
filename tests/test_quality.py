"""Coverage reporting and the censoring warning."""

from datetime import date, timedelta

import pytest

from trends_research_cli.quality import (
    censoring_warnings,
    coverage,
    freshness_warning,
)
from trends_research_cli.record import Record

START = date(2026, 7, 1)


def series(*values: float, term: str = "flu", group: str = "") -> list[Record]:
    return [
        Record(
            START + timedelta(days=i), START + timedelta(days=i), term, group, v
        )
        for i, v in enumerate(values)
    ]


def test_coverage_counts_zeros_and_summarises_the_spread():
    stats = coverage(series(0.0, 10.0, 20.0, 0.0))[0]

    assert stats.count == 4
    assert stats.zero_count == 2
    assert stats.pct_zero == 50.0
    assert stats.median == 5.0
    assert stats.maximum == 20.0


def test_the_longest_zero_run_is_reported():
    """A long flat stretch reads differently from scattered suppression."""
    stats = coverage(series(0.0, 0.0, 0.0, 5.0, 0.0))[0]

    assert stats.longest_zero_run == 3


def test_coverage_is_reported_per_term_and_group():
    records = series(1.0, 2.0, term="flu") + series(0.0, 0.0, term="vaccine")

    stats = {s.term: s for s in coverage(records)}

    assert stats["flu"].pct_zero == 0.0
    assert stats["vaccine"].pct_zero == 100.0


def test_a_mostly_zero_series_triggers_a_censoring_warning():
    """Acceptance test 11: over 50% zero must warn."""
    stats = coverage(series(0.0, 0.0, 0.0, 1.0))

    warnings = censoring_warnings(stats)

    assert len(warnings) == 1
    assert "75.0% zero" in warnings[0]
    assert "suppressed" in warnings[0]


def test_a_populated_series_does_not_warn():
    assert censoring_warnings(coverage(series(1.0, 2.0, 3.0, 0.0))) == []


def test_the_threshold_is_exclusive_so_exactly_half_does_not_warn():
    assert censoring_warnings(coverage(series(0.0, 0.0, 1.0, 2.0))) == []


def test_empty_input_yields_no_coverage():
    assert coverage([]) == []


@pytest.mark.parametrize(
    ("values", "expected"),
    [((1.0, 2.0), 1.5), ((1.0, 2.0, 3.0), 2.0), ((5.0,), 5.0)],
)
def test_median_handles_both_parities(values, expected):
    assert coverage(series(*values))[0].median == expected


def test_a_range_running_up_to_today_warns_that_it_is_still_settling():
    """A partial UTC day is a normal-looking share, not an obvious gap."""
    warning = freshness_warning(date(2026, 8, 10), today=date(2026, 8, 10))

    assert warning is not None
    assert "UTC" in warning and "provisional" in warning


def test_a_settled_range_does_not_warn():
    assert freshness_warning(date(2026, 7, 1), today=date(2026, 8, 10)) is None
