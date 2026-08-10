"""Splitting long requests under the point ceiling."""

from datetime import date

import pytest

from gtrendscli.chunking import chunk_periods
from gtrendscli.dates import DateRange, Interval, clamp


def periods(start: date, end: date, interval=Interval.DAY):
    return clamp(DateRange(start, end), interval).periods


def test_a_short_range_is_a_single_chunk():
    chunks = chunk_periods(
        periods(date(2026, 7, 1), date(2026, 7, 31)), terms=1
    )

    assert chunks == [DateRange(date(2026, 7, 1), date(2026, 7, 31))]


def test_a_long_range_is_split_under_the_ceiling():
    """Acceptance test 10: 2,000 days must chunk rather than fail."""
    chunks = chunk_periods(
        periods(date(2021, 1, 1), date(2026, 6, 23)), terms=1, max_points=380
    )

    assert len(chunks) > 1
    assert all((chunk.end - chunk.start).days + 1 <= 380 for chunk in chunks)


def test_chunks_are_contiguous_and_cover_the_whole_range():
    """Gaps or overlaps would silently corrupt a concatenated series."""
    whole = periods(date(2021, 1, 1), date(2026, 6, 23))

    chunks = chunk_periods(whole, terms=1, max_points=380)

    assert chunks[0].start == whole[0].start
    assert chunks[-1].end == whole[-1].end
    for earlier, later in zip(chunks, chunks[1:], strict=False):
        assert (later.start - earlier.end).days == 1


@pytest.mark.parametrize("terms", [1, 2, 5])
def test_the_ceiling_counts_terms_times_points(terms):
    """More terms means fewer days per request: the limit is the product."""
    whole = periods(date(2021, 1, 1), date(2026, 6, 23))

    for chunk in chunk_periods(whole, terms=terms, max_points=380):
        points = (chunk.end - chunk.start).days + 1
        assert points * terms <= 380


def test_coarse_intervals_fit_far_more_calendar_time_per_chunk():
    """The ceiling counts returned points, not days, so months pack densely."""
    months = periods(date(2000, 1, 1), date(2026, 12, 31), Interval.MONTH)

    chunks = chunk_periods(months, terms=1, max_points=380)

    assert len(chunks) == 1


def test_more_terms_than_the_ceiling_is_refused():
    with pytest.raises(ValueError, match="too many terms"):
        chunk_periods(periods(date(2026, 7, 1), date(2026, 7, 2)), terms=500)
