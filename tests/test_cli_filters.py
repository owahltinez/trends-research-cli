"""`--category`, `--category-id` and `--property` at the command level.

The load-bearing test here is the refusal: `timelinesForHealth` accepts both
filters and returns unfiltered data, so offering them on a time series would
answer a filtered question with the wrong numbers.
"""

import json

from click.testing import CliRunner
from fakes import FakeTransport

from trends_research_cli.api.client import Client, Response
from trends_research_cli.cli import main

RUNNER = CliRunner()

BASE = ["series", "/m/0cycc", "--geo", "US"]


def run(args, *responses):
    transport = FakeTransport(*responses)
    client = Client(transport, sleep=lambda _: None)
    return RUNNER.invoke(main, args, obj=client), transport


def regions_body(**values: int) -> dict:
    return {
        "regions": [
            {"regionCode": code, "regionName": code, "value": value}
            for code, value in values.items()
        ]
    }


REGIONS = Response(200, regions_body(**{"US-CA": 90, "US-NY": 70}))


# --- the guard ---------------------------------------------------------------


def test_a_time_series_refuses_the_filters_it_would_silently_ignore():
    """Verified live: identical values for every category and property,
    including ids that 500 on other endpoints."""
    for flag, value in (
        ("--category", "/Health"),
        ("--category-id", "45"),
        ("--property", "news"),
    ):
        result, transport = run(
            [*BASE, "--from", "2025-07-01", "--to", "2025-07-02", flag, value]
        )

        assert result.exit_code == 1, flag
        assert "unfiltered" in result.output, flag
        assert transport.calls == [], "refused before spending a request"


def test_by_year_refuses_them_too():
    result, transport = run(
        [
            *BASE,
            "--from",
            "07-21",
            "--by",
            "year",
            "--years",
            "2024",
            "--category",
            "/Health",
        ]
    )

    assert result.exit_code == 1
    assert transport.calls == []


# --- the flags where they do work --------------------------------------------


def test_a_category_path_is_resolved_and_sent_by_id():
    result, transport = run(
        [
            *BASE,
            "--from",
            "2025-07",
            "--by",
            "region",
            "--category",
            "/Health/Health Conditions",
        ],
        REGIONS,
    )

    assert result.exit_code == 0
    assert dict(transport.calls[0][1])["restrictions.category"] == "419"


def test_a_bare_leaf_name_resolves_too():
    _, transport = run(
        [
            *BASE,
            "--from",
            "2025-07",
            "--by",
            "region",
            "--category",
            "Health Conditions",
        ],
        REGIONS,
    )

    assert dict(transport.calls[0][1])["restrictions.category"] == "419"


def test_the_resolved_path_is_echoed_so_the_output_is_self_describing():
    result, _ = run(
        [
            *BASE,
            "--from",
            "2025-07",
            "--by",
            "region",
            "--category",
            "Health Conditions",
        ],
        REGIONS,
    )

    assert "419 /Health/Health Conditions" in result.output


def test_choosing_a_parent_says_what_it_sweeps_in():
    """A parent's results include its descendants, which is easy to miss."""
    result, _ = run(
        [*BASE, "--from", "2025-07", "--by", "region", "--category", "/Health"],
        REGIONS,
    )

    assert "sub-categories beneath it" in result.output
    assert "Health Conditions" in result.output


def test_an_unknown_category_is_refused_before_a_request():
    result, transport = run(
        [
            *BASE,
            "--from",
            "2025-07",
            "--by",
            "region",
            "--category",
            "/Health/Not A Real Thing",
        ]
    )

    assert result.exit_code == 1
    assert "no category matches" in result.output
    assert transport.calls == [], "the API would answer this with a 500"


def test_a_typo_gets_a_suggestion():
    result, _ = run(
        [*BASE, "--from", "2025-07", "--by", "region", "--category", "helth"]
    )

    assert "Health" in result.output


def test_a_numeric_id_is_validated_like_a_path():
    """The valid ids are a known finite set, so an unknown one is refused here
    rather than spent on a request the API answers with an opaque 500."""
    result, transport = run(
        [
            *BASE,
            "--from",
            "2025-07",
            "--by",
            "region",
            "--category-id",
            "99999",
        ]
    )

    assert result.exit_code == 1
    assert "not in the taxonomy" in result.output
    assert "upgrade trends_research_cli" in result.output, (
        "and says how to fix a stale copy"
    )
    assert transport.calls == []


def test_a_valid_numeric_id_resolves_to_its_path():
    result, transport = run(
        [
            *BASE,
            "--from",
            "2025-07",
            "--by",
            "region",
            "--category-id",
            "419",
            "--json",
        ],
        REGIONS,
    )

    assert result.exit_code == 0
    assert dict(transport.calls[0][1])["restrictions.category"] == "419"

    payload = json.loads(result.output)
    assert payload["meta"]["category"] == "419 /Health/Health Conditions"
    assert any("sits inside /Health" in n for n in payload["notes"])


def test_the_two_category_flags_are_mutually_exclusive():
    result, transport = run(
        [
            *BASE,
            "--from",
            "2025-07",
            "--by",
            "region",
            "--category",
            "/Health",
            "--category-id",
            "45",
        ]
    )

    assert result.exit_code == 1
    assert "not both" in result.output
    assert transport.calls == []


def test_property_reaches_the_wire_and_shopping_is_translated():
    for given, sent in (("news", "news"), ("shopping", "froogle"), ("web", "")):
        _, transport = run(
            [*BASE, "--from", "2025-07", "--by", "region", "--property", given],
            REGIONS,
        )
        assert dict(transport.calls[0][1])["restrictions.property"] == sent, (
            given
        )


def test_an_unknown_property_is_refused_by_the_choice_type():
    result, transport = run(
        [*BASE, "--from", "2025-07", "--by", "region", "--property", "tiktok"]
    )

    assert result.exit_code == 1
    assert transport.calls == []


# --- queries and topics ------------------------------------------------------


def test_queries_takes_the_filters():
    result, transport = run(
        [
            "queries",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07",
            "--category",
            "/Health",
            "--property",
            "news",
            "--json",
        ],
        Response(200, {"item": [{"title": "flu", "value": 100}]}),
    )

    sent = dict(transport.calls[0][1])
    assert sent["restrictions.category"] == "45"
    assert sent["restrictions.property"] == "news"

    payload = json.loads(result.output)
    assert payload["meta"]["category"] == "45 /Health"
    assert payload["meta"]["property"] == "news"


def test_topics_takes_them_too():
    _, transport = run(
        [
            "topics",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07",
            "--category-id",
            "419",
        ],
        Response(200, {"item": []}),
    )

    assert dict(transport.calls[0][1])["restrictions.category"] == "419"


# --- the categories command --------------------------------------------------


def test_categories_find_lists_paths_with_descendant_counts():
    result = RUNNER.invoke(
        main, ["categories", "--find", "health cond"], obj=object()
    )

    assert result.exit_code == 0
    assert "419  /Health/Health Conditions" in result.output
    assert "+31 below" in result.output


def test_categories_show_spells_out_what_is_included():
    result = RUNNER.invoke(
        main, ["categories", "--show", "/Health"], obj=object()
    )

    assert "45  /Health" in result.output
    assert "sub-categories" in result.output


def test_categories_show_reports_both_routes_for_a_shared_category():
    result = RUNNER.invoke(
        main, ["categories", "--show", "Animated Films"], obj=object()
    )

    assert "also reachable as" in result.output


def test_categories_warns_that_the_taxonomy_is_old():
    """No AI, crypto or streaming category exists; better to say so."""
    result = RUNNER.invoke(
        main, ["categories", "--find", "health"], obj=object()
    )

    assert "predates about 2012" in result.output


def test_categories_needs_no_network_or_credentials():
    result = RUNNER.invoke(main, ["categories", "--show", "45"])

    assert result.exit_code == 0
    assert "/Health" in result.output


def test_choosing_a_child_warns_that_it_overlaps_its_parents():
    """Comparing this run against one filtered to /Health would compare a set
    with a superset of itself -- the same error as dividing by a control."""
    result, _ = run(
        [
            *BASE,
            "--from",
            "2025-07",
            "--by",
            "region",
            "--category",
            "Health Conditions",
            "--json",
        ],
        REGIONS,
    )

    notes = json.loads(result.output)["notes"]
    assert any("sits inside /Health" in n for n in notes)
    assert any("not independent" in n for n in notes)


def test_a_top_level_category_says_nothing_about_containers():
    result, _ = run(
        [
            *BASE,
            "--from",
            "2025-07",
            "--by",
            "region",
            "--category",
            "/Health",
            "--json",
        ],
        REGIONS,
    )

    assert not any(
        "sits inside" in n for n in json.loads(result.output)["notes"]
    )


def test_categories_show_reports_containment_both_ways():
    result = RUNNER.invoke(
        main, ["categories", "--show", "Health Conditions"], obj=object()
    )

    assert "contained by: /Health" in result.output
    assert "sub-categories" in result.output
