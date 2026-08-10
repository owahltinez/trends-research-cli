"""Turning API responses into records.

`timelinesForHealth` labels its points differently depending on the resolution
it was asked for, and never states the period a point covers. Both are
reconstructed here so every record carries its true coverage.
"""

from datetime import date

import pytest

from gtrendscli.api.parse import parse_timelines
from gtrendscli.dates import Interval


def body(points: list[tuple[str, float]], term: str = "flu") -> dict:
    return {
        "lines": [
            {
                "term": term,
                "points": [
                    {"date": text, "value": value} for text, value in points
                ],
            }
        ]
    }


def test_daily_points_use_the_long_date_format():
    records = parse_timelines(
        body([("Jul 01 2025", 152.8), ("Jul 02 2025", 129.4)]),
        interval=Interval.DAY,
    )

    assert [r.date_start for r in records] == [
        date(2025, 7, 1),
        date(2025, 7, 2),
    ]
    assert all(r.date_start == r.date_end for r in records)
    assert [r.value for r in records] == [152.8, 129.4]
    assert {r.term for r in records} == {"flu"}


def test_monthly_points_drop_the_day_and_span_the_whole_month():
    records = parse_timelines(
        body([("Jul 2025", 4000.5), ("Aug 2025", 4100.5)]),
        interval=Interval.MONTH,
    )

    assert records[0].date_start == date(2025, 7, 1)
    assert records[0].date_end == date(2025, 7, 31)
    assert records[1].date_end == date(2025, 8, 31)


def test_weekly_points_span_seven_days_from_their_label():
    records = parse_timelines(
        body([("Jun 29 2025", 121.6)]), interval=Interval.WEEK
    )

    assert records[0].date_start == date(2025, 6, 29)
    assert records[0].date_end == date(2025, 7, 5)


def test_several_terms_are_flattened_into_one_record_list():
    payload = {
        "lines": [
            body([("Jul 01 2025", 10.0)], term="flu")["lines"][0],
            body([("Jul 01 2025", 20.0)], term="vaccine")["lines"][0],
        ]
    }

    records = parse_timelines(payload, interval=Interval.DAY)

    assert [(r.term, r.value) for r in records] == [
        ("flu", 10.0),
        ("vaccine", 20.0),
    ]


def test_group_is_stamped_on_every_record():
    records = parse_timelines(
        body([("Jul 01 2025", 10.0)]), interval=Interval.DAY, group="US-CA"
    )

    assert records[0].group == "US-CA"


def test_an_empty_response_yields_no_records():
    assert parse_timelines({}, interval=Interval.DAY) == []


def test_an_unrecognised_date_label_is_an_error_not_a_guess():
    """Silently dropping a point would understate coverage."""
    with pytest.raises(ValueError, match="date"):
        parse_timelines(body([("2025-07-01", 10.0)]), interval=Interval.DAY)


def test_yearly_points_are_labelled_with_the_bare_year():
    records = parse_timelines(body([("2024", 4000.5)]), interval=Interval.YEAR)

    assert records[0].date_start == date(2024, 1, 1)
    assert records[0].date_end == date(2024, 12, 31)
