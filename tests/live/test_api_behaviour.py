"""The undocumented API behaviours this tool depends on.

Every claim the tool encodes about this API is asserted here against the real
thing, so the knowledge cannot decay into folklore. These tests assert
structure, never values: the API is a sampled product and its numbers move.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta

import pytest

from trends_research_cli.api.endpoints import Endpoint, build_params
from trends_research_cli.dates import DateRange, Interval

pytestmark = pytest.mark.live

TERM = "influenza"


def _kgsearch(ids: str, api_key: str) -> urllib.request.Request:
    """A kgsearch request with the key in a header, never in the URL."""
    query = urllib.parse.urlencode({"ids": ids})
    return urllib.request.Request(
        f"https://kgsearch.googleapis.com/v1/entities:search?{query}",
        headers={"x-goog-api-key": api_key},
    )


JULY_2025 = DateRange(date(2025, 7, 1), date(2025, 7, 31))


def _restriction_params(start: str, end: str, term_key: str = "term"):
    return [
        (term_key, TERM),
        ("restrictions.startDate", start),
        ("restrictions.endDate", end),
        ("restrictions.geo", "US"),
    ]


@pytest.mark.parametrize("endpoint", list(Endpoint))
def test_every_endpoint_accepts_the_parameter_family_we_build(endpoint, fetch):
    interval = Interval.DAY if endpoint is Endpoint.TIMELINES else None
    params = build_params(
        endpoint, terms=[TERM], geo="US", span=JULY_2025, interval=interval
    )

    status, _ = fetch(endpoint, params)

    assert status == 200, f"{endpoint.value} rejected the family we build"


def test_timelines_rejects_restriction_style_parameters(fetch):
    """The trap: right values, wrong family, no useful message."""
    status, _ = fetch(
        Endpoint.TIMELINES,
        [
            *_restriction_params("2025-07", "2025-07", term_key="terms"),
            ("timelineResolution", "day"),
        ],
    )

    assert status == 400


def test_singular_term_endpoints_reject_plural_spelling(fetch):
    status, _ = fetch(
        Endpoint.REGIONS, _restriction_params("2025-07", "2025-07", "terms")
    )

    assert status == 400


def test_regions_honours_day_granular_dates(fetch):
    """`regions` accepts full dates and means them, unlike its siblings."""
    _, five_days = fetch(
        Endpoint.REGIONS, _restriction_params("2025-07-01", "2025-07-05")
    )
    _, whole_month = fetch(
        Endpoint.REGIONS, _restriction_params("2025-07", "2025-07")
    )

    def by_code(body):
        return {r["regionCode"]: r["value"] for r in body["regions"]}

    assert by_code(five_days) != by_code(whole_month), (
        "identical answers would mean full dates are silently widened"
    )


@pytest.mark.parametrize(
    "endpoint",
    [
        Endpoint.TOP_QUERIES,
        Endpoint.RISING_QUERIES,
        Endpoint.TOP_TOPICS,
        Endpoint.RISING_TOPICS,
        Endpoint.GRAPH,
    ],
)
def test_month_granular_endpoints_reject_sub_month_ranges(endpoint, fetch):
    """Note the status: a caller error surfaced as a 500, so never retried."""
    term_key = "terms" if endpoint is Endpoint.GRAPH else "term"
    status, _ = fetch(
        endpoint, _restriction_params("2025-07-01", "2025-07-05", term_key)
    )

    assert status == 500


def _timeline_dates(body):
    return [point["date"] for point in body["lines"][0]["points"]]


def test_week_buckets_start_on_sunday_and_can_precede_the_request(fetch):
    """Justifies both the Sunday default and the clamp rule for weeks."""
    span = DateRange(date(2025, 7, 1), date(2025, 8, 31))
    _, body = fetch(
        Endpoint.TIMELINES,
        build_params(
            Endpoint.TIMELINES,
            terms=[TERM],
            geo="US",
            span=span,
            interval=Interval.WEEK,
        ),
    )

    parsed = [
        datetime.strptime(text, "%b %d %Y").date()
        for text in _timeline_dates(body)
    ]

    assert all(day.weekday() == 6 for day in parsed), "weeks start on Sunday"
    assert parsed[0] < span.start, "the first bucket bleeds before the request"


def test_month_resolution_bleeds_across_a_short_request(fetch):
    """Why `clamp` errors instead of returning a widened answer."""
    _, body = fetch(
        Endpoint.TIMELINES,
        build_params(
            Endpoint.TIMELINES,
            terms=[TERM],
            geo="US",
            span=DateRange(date(2025, 7, 1), date(2025, 7, 3)),
            interval=Interval.MONTH,
        ),
    )

    # A three-day request answered with the whole of July, and the coarser
    # response format drops the day entirely.
    assert _timeline_dates(body) == ["Jul 2025"]


def test_graph_ignores_the_span_granularity_and_returns_daily_points(fetch):
    """It has no resolution parameter and picks one from the span."""
    _, body = fetch(
        Endpoint.GRAPH,
        _restriction_params("2024-01", "2024-06", term_key="terms"),
    )

    points = body["lines"][0]["points"]

    assert len(points) > 100, "a six-month request comes back daily"
    date.fromisoformat(points[0]["date"]), "graph labels ISO, not 'Jul 01 2025'"


def test_kgsearch_rejects_the_prefixed_id_it_returns(fetch, api_key):
    """`@id` comes back as `kg:/m/...` but `ids` wants the bare MID."""

    def kg(ids: str) -> int:
        try:
            with urllib.request.urlopen(
                _kgsearch(ids, api_key), timeout=30
            ) as (response):
                body = json.loads(response.read())
                return len(body.get("itemListElement", []))
        except urllib.error.HTTPError as exc:
            return -exc.code

    assert kg("/m/087t7g") == 1, "the bare MID resolves"
    assert kg("kg:/m/087t7g") == -400, "the prefixed form is rejected"


def test_trends_serves_entities_that_kgsearch_has_never_heard_of(
    fetch, api_key
):
    """Why `entity find` consults both indexes, not just kgsearch."""
    with urllib.request.urlopen(
        _kgsearch("/m/0cycc", api_key), timeout=30
    ) as response:
        assert json.loads(response.read()).get("itemListElement") == []

    status, body = fetch(
        Endpoint.TIMELINES,
        build_params(
            Endpoint.TIMELINES,
            terms=["/m/0cycc"],
            geo="US",
            span=JULY_2025,
            interval=Interval.DAY,
        ),
    )

    assert status == 200
    assert any(p["value"] > 0 for p in body["lines"][0]["points"])


def test_days_are_binned_in_utc_not_local_time(fetch):
    """Google documents UTC binning for daily Trends data, and this API has no
    timezone parameter to override it. Corroborated here: a range ending today
    comes back labelled with the current *UTC* date, which in US Pacific time
    has not started yet."""
    today = datetime.now(UTC).date()

    status, body = fetch(
        Endpoint.TIMELINES,
        build_params(
            Endpoint.TIMELINES,
            terms=["influenza"],
            geo="US",
            # Long enough to clear the horizon below; a short window ending
            # today is refused outright.
            span=DateRange(today - timedelta(days=20), today),
            interval=Interval.DAY,
        ),
    )

    assert status == 200
    labels = [
        datetime.strptime(point["date"], "%b %d %Y").date()
        for point in body["lines"][0]["points"]
    ]
    assert today in labels, "the current UTC day is already served"


def test_the_data_horizon_sits_days_behind_the_current_utc_date(fetch):
    """The inconsistency behind `freshness_warning`.

    A short window ending inside the last couple of days is rejected outright,
    but a long window spanning the same days returns them anyway, with values
    that look entirely ordinary. Both facts matter: the first tells us where
    the horizon is, the second is how a phantom late spike gets published.
    """
    today = datetime.now(UTC).date()

    def four_days_ending(end):
        status, _ = fetch(
            Endpoint.TIMELINES,
            build_params(
                Endpoint.TIMELINES,
                terms=["influenza"],
                geo="US",
                span=DateRange(end - timedelta(days=3), end),
                interval=Interval.DAY,
            ),
        )
        return status

    assert four_days_ending(today) == 400, "too recent to answer"
    assert four_days_ending(today - timedelta(days=5)) == 200, "settled"


def test_year_resolution_is_accepted_and_labelled_bare(fetch):
    _, body = fetch(
        Endpoint.TIMELINES,
        build_params(
            Endpoint.TIMELINES,
            terms=["influenza"],
            geo="US",
            span=DateRange(date(2022, 1, 1), date(2024, 12, 31)),
            interval=Interval.YEAR,
        ),
    )

    assert [p["date"] for p in body["lines"][0]["points"]] == [
        "2022",
        "2023",
        "2024",
    ]


def test_there_is_no_hourly_resolution(fetch):
    """Confirms the documented absence rather than assuming it."""
    status, _ = fetch(
        Endpoint.TIMELINES,
        [
            ("terms", TERM),
            ("time.startDate", "2025-07-01"),
            ("time.endDate", "2025-07-03"),
            ("timelineResolution", "hour"),
            ("geoRestriction.country", "US"),
        ],
    )

    assert status == 400


def test_a_bare_number_is_accepted_as_a_nielsen_dma(fetch):
    """DMAs are US media markets; 501 is New York."""
    status, body = fetch(
        Endpoint.TIMELINES,
        build_params(
            Endpoint.TIMELINES,
            terms=[TERM],
            geo="501",
            span=DateRange(date(2025, 7, 1), date(2025, 7, 3)),
            interval=Interval.DAY,
        ),
    )

    assert status == 200
    assert len(body["lines"][0]["points"]) == 3


def test_property_changes_the_answer_on_the_restriction_family(fetch):
    """Why `--property` exists: the vertical picks different data."""

    def regions(prop):
        _, body = fetch(
            Endpoint.REGIONS,
            build_params(
                Endpoint.REGIONS,
                terms=[TERM],
                geo="US",
                span=DateRange(date(2025, 1, 1), date(2025, 3, 31)),
                trends_property=prop,
            ),
        )
        return {r["regionCode"]: r["value"] for r in body["regions"]}

    assert regions("web") != regions("news"), "the vertical must matter"
    assert regions("news") != regions("youtube")


def test_timelines_accepts_property_and_category_but_ignores_them(fetch):
    """The reason `series` refuses these flags rather than forwarding them.

    A 200 proves nothing here: the endpoint returns identical values for every
    property and category, including a category id that 500s on `regions`.
    """

    def timeline(extra):
        params = build_params(
            Endpoint.TIMELINES,
            terms=[TERM],
            geo="US",
            span=DateRange(date(2025, 7, 1), date(2025, 7, 4)),
            interval=Interval.DAY,
        )
        status, body = fetch(Endpoint.TIMELINES, params + extra)
        assert status == 200
        return [p["value"] for p in body["lines"][0]["points"]]

    plain = timeline([])
    assert timeline([("restrictions.property", "news")]) == plain
    assert timeline([("restrictions.category", "184")]) == plain
    assert timeline([("restrictions.category", "99999999")]) == plain


def test_an_unknown_category_is_rejected_by_the_restriction_family(fetch):
    """So local validation saves a request, and a 500 here is a caller error."""
    status, _ = fetch(
        Endpoint.REGIONS,
        build_params(
            Endpoint.REGIONS,
            terms=[TERM],
            geo="US",
            span=DateRange(date(2025, 1, 1), date(2025, 3, 31)),
            category=88888,
        ),
    )

    assert status == 500, "a caller error reported as a server error, again"


def test_a_parent_category_includes_its_descendants(fetch):
    """The containment that makes the vendored tree worth keeping."""

    def queries(category):
        _, body = fetch(
            Endpoint.TOP_QUERIES,
            build_params(
                Endpoint.TOP_QUERIES,
                terms=["batman"],
                geo="US",
                span=DateRange(date(2025, 1, 1), date(2025, 6, 30)),
                category=category,
            ),
        )
        return {i["title"] for i in body.get("item", [])}

    comics = queries(318)
    cartoons = queries(319)
    parent = queries(316)

    assert parent & (comics | cartoons), (
        "the parent must draw on the children beneath it"
    )
