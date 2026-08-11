"""Per-endpoint parameter families.

The API uses three mutually incompatible parameter families across its
endpoints, and the wrong one returns a bare 400 with no hint. These tests pin
each family down so the knowledge cannot be lost again.
"""

from datetime import date

import pytest

from trends_research_cli.api.endpoints import Endpoint, build_params, build_url
from trends_research_cli.dates import DateRange, Interval

JULY = DateRange(date(2026, 7, 1), date(2026, 7, 31))


def test_timelines_uses_plural_terms_and_full_dates():
    params = build_params(
        Endpoint.TIMELINES,
        terms=["/m/0cycc", "/m/07__7"],
        geo="US",
        span=JULY,
        interval=Interval.DAY,
    )

    assert params == [
        ("terms", "/m/0cycc"),
        ("terms", "/m/07__7"),
        ("time.startDate", "2026-07-01"),
        ("time.endDate", "2026-07-31"),
        ("timelineResolution", "day"),
        ("geoRestriction.country", "US"),
    ]


def test_timelines_switches_to_region_key_for_subnational_geo():
    params = dict(
        build_params(
            Endpoint.TIMELINES,
            terms=["/m/0cycc"],
            geo="US-AK",
            span=JULY,
            interval=Interval.DAY,
        )
    )

    assert params["geoRestriction.region"] == "US-AK"
    assert "geoRestriction.country" not in params


@pytest.mark.parametrize(
    "endpoint",
    [
        Endpoint.TOP_QUERIES,
        Endpoint.RISING_QUERIES,
        Endpoint.TOP_TOPICS,
        Endpoint.RISING_TOPICS,
    ],
)
def test_query_and_topic_endpoints_take_singular_term_and_month_dates(endpoint):
    params = build_params(endpoint, terms=["/m/0cycc"], geo="US", span=JULY)

    assert params == [
        ("term", "/m/0cycc"),
        ("restrictions.startDate", "2026-07"),
        ("restrictions.endDate", "2026-07"),
        ("restrictions.geo", "US"),
    ]


def test_regions_takes_restriction_names_but_day_granular_dates():
    """Verified live: `regions` is the odd one out.

    It uses the restriction-style parameter names yet honours full dates, while
    its siblings reject a sub-month range outright. Nothing about the naming
    predicts this, which is why the families are a table rather than a rule.
    """
    params = build_params(
        Endpoint.REGIONS, terms=["/m/0cycc"], geo="US", span=JULY
    )

    assert params == [
        ("term", "/m/0cycc"),
        ("restrictions.startDate", "2026-07-01"),
        ("restrictions.endDate", "2026-07-31"),
        ("restrictions.geo", "US"),
    ]


@pytest.mark.parametrize(
    "endpoint",
    [Endpoint.REGIONS, Endpoint.TOP_QUERIES, Endpoint.RISING_TOPICS],
)
def test_singular_term_endpoints_reject_multiple_terms(endpoint):
    with pytest.raises(ValueError, match="one term"):
        build_params(
            endpoint, terms=["/m/0cycc", "/m/07__7"], geo="US", span=JULY
        )


def test_graph_mixes_plural_terms_with_restriction_dates():
    """The one endpoint crossing families; why they must be data, not a rule."""
    params = build_params(
        Endpoint.GRAPH, terms=["/m/0cycc", "/m/07__7"], geo="US", span=JULY
    )

    assert params == [
        ("terms", "/m/0cycc"),
        ("terms", "/m/07__7"),
        ("restrictions.startDate", "2026-07"),
        ("restrictions.endDate", "2026-07"),
        ("restrictions.geo", "US"),
    ]


def test_params_carry_only_what_the_endpoint_was_given():
    """Parameters are archived and put in receipts, so nothing may appear in
    them that the caller did not supply. Credentials are added by the
    transport; tests/test_transport.py is what proves they stay there."""
    for endpoint in Endpoint:
        params = build_params(
            endpoint,
            terms=["/m/0cycc"],
            geo="US",
            span=JULY,
            interval=Interval.DAY,
        )
        supplied = {
            "/m/0cycc",
            "US",
            "2026-07-01",
            "2026-07-31",
            "2026-07",
            "day",
        }
        assert {value for _, value in params} <= supplied


def test_timelines_requires_an_interval():
    with pytest.raises(ValueError, match="interval"):
        build_params(
            Endpoint.TIMELINES, terms=["/m/0cycc"], geo="US", span=JULY
        )


def test_url_is_built_from_the_documented_base():
    assert build_url(Endpoint.TIMELINES) == (
        "https://www.googleapis.com/trends/v1beta/timelinesForHealth"
    )


def test_a_numeric_geo_is_sent_as_a_nielsen_dma():
    """DMAs are US media markets, and take a third geo key of their own."""
    params = dict(
        build_params(
            Endpoint.TIMELINES,
            terms=["/m/0cycc"],
            geo="501",
            span=JULY,
            interval=Interval.DAY,
        )
    )

    assert params["geoRestriction.dma"] == "501"
    assert "geoRestriction.country" not in params
    assert "geoRestriction.region" not in params


def test_more_terms_than_the_api_accepts_is_refused_locally():
    with pytest.raises(ValueError, match="30"):
        build_params(
            Endpoint.TIMELINES,
            terms=[f"/m/{n}" for n in range(31)],
            geo="US",
            span=JULY,
            interval=Interval.DAY,
        )


@pytest.mark.parametrize("term", ["", "   ", "\t"])
def test_a_blank_term_is_refused_before_a_request_is_spent(term):
    """The API answers this with a bare 400; local refusal costs no quota."""
    with pytest.raises(ValueError, match="blank"):
        build_params(
            Endpoint.TIMELINES,
            terms=[term],
            geo="US",
            span=JULY,
            interval=Interval.DAY,
        )


def test_a_blank_term_among_good_ones_names_which():
    with pytest.raises(ValueError, match="term 2 is blank"):
        build_params(
            Endpoint.TIMELINES,
            terms=["/m/0cycc", "  "],
            geo="US",
            span=JULY,
            interval=Interval.DAY,
        )


@pytest.mark.parametrize("geo", ["", "  "])
def test_a_blank_geo_is_refused_locally(geo):
    with pytest.raises(ValueError, match="geo is blank"):
        build_params(
            Endpoint.TIMELINES,
            terms=["/m/0cycc"],
            geo=geo,
            span=JULY,
            interval=Interval.DAY,
        )


def test_a_control_character_in_geo_is_refused():
    """It would forge a comment line in the output header."""
    with pytest.raises(ValueError, match="control character"):
        build_params(
            Endpoint.TIMELINES,
            terms=["/m/0cycc"],
            geo="US\nforged",
            span=JULY,
            interval=Interval.DAY,
        )


# --- category and property ---------------------------------------------------


def test_restriction_family_endpoints_carry_category_and_property():
    params = dict(
        build_params(
            Endpoint.TOP_QUERIES,
            terms=["/m/0cycc"],
            geo="US",
            span=JULY,
            category=419,
            trends_property="news",
        )
    )

    assert params["restrictions.category"] == "419"
    assert params["restrictions.property"] == "news"


def test_regions_carries_them_too():
    params = dict(
        build_params(
            Endpoint.REGIONS,
            terms=["/m/0cycc"],
            geo="US",
            span=JULY,
            category=45,
            trends_property="youtube",
        )
    )

    assert params["restrictions.category"] == "45"
    assert params["restrictions.property"] == "youtube"


def test_shopping_is_translated_to_the_api_legacy_name():
    """The API still calls it `froogle`; nobody else has for fifteen years."""
    params = dict(
        build_params(
            Endpoint.REGIONS,
            terms=["/m/0cycc"],
            geo="US",
            span=JULY,
            trends_property="shopping",
        )
    )

    assert params["restrictions.property"] == "froogle"


def test_web_is_sent_as_the_empty_string_the_api_expects():
    params = dict(
        build_params(
            Endpoint.REGIONS,
            terms=["/m/0cycc"],
            geo="US",
            span=JULY,
            trends_property="web",
        )
    )

    assert params["restrictions.property"] == ""


def test_timelines_refuses_them_because_it_would_ignore_them():
    """Verified live: `timelinesForHealth` returns identical values for every
    category and property, including nonsense ones. Accepting the flag would
    hand back a confident, unfiltered answer to a filtered question."""
    for extra in ({"category": 419}, {"trends_property": "news"}):
        with pytest.raises(ValueError, match="ignores"):
            build_params(
                Endpoint.TIMELINES,
                terms=["/m/0cycc"],
                geo="US",
                span=JULY,
                interval=Interval.DAY,
                **extra,
            )


def test_category_zero_is_sent_since_it_equals_no_filter():
    """0 is 'All categories'; sending it and omitting it are equivalent."""
    params = dict(
        build_params(
            Endpoint.REGIONS,
            terms=["/m/0cycc"],
            geo="US",
            span=JULY,
            category=0,
        )
    )

    assert params["restrictions.category"] == "0"


def test_neither_appears_when_not_asked_for():
    params = dict(
        build_params(Endpoint.REGIONS, terms=["/m/0cycc"], geo="US", span=JULY)
    )

    assert "restrictions.category" not in params
    assert "restrictions.property" not in params
