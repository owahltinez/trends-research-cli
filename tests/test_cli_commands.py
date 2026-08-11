"""`doctor`, `entity`, `queries`, `topics` and `check`, against fakes."""

import json
import math

from click.testing import CliRunner
from fakes import FakeTransport, timeline_body

from trends_research_cli.api.client import Client, Response
from trends_research_cli.cli import main
from trends_research_cli.commands.check import _rank_agreement
from trends_research_cli.credentials import CredentialsError

RUNNER = CliRunner()


def run(args, *responses, obj=None):
    transport = FakeTransport(*responses)
    client = obj if obj is not None else Client(transport, sleep=lambda _: None)
    return RUNNER.invoke(main, args, obj=client), transport


def kg_body(*entries: tuple[str, str]) -> dict:
    return {
        "itemListElement": [
            {
                "resultScore": 100.0,
                "result": {"@id": f"kg:{mid}", "name": name},
            }
            for mid, name in entries
        ]
    }


def topics_body(*entries: tuple[str, str]) -> dict:
    return {
        "item": [
            {"title": name, "mid": mid, "value": 100} for mid, name in entries
        ]
    }


# --- doctor -----------------------------------------------------------------


def test_doctor_reports_a_healthy_setup():
    result, _ = run(
        ["doctor"], Response(200, {"regions": []}), Response(200, kg_body())
    )

    assert result.exit_code == 0
    assert result.output.count("PASS") == 3


def test_doctor_distinguishes_not_allow_listed_from_a_bad_key():
    """Acceptance test 14: both surface as an unhelpful status."""
    # kgsearch is still probed after a Trends failure: both answers are useful.
    rejected, _ = run(["doctor"], Response(400, None), Response(200, kg_body()))
    refused, _ = run(["doctor"], Response(403, None), Response(200, kg_body()))

    assert "not allow-listed" in rejected.output
    assert "request access" in rejected.output.lower()
    assert "may be invalid" in refused.output
    assert rejected.exit_code == 1 and refused.exit_code == 1


def test_doctor_runs_and_explains_itself_without_any_key():
    """The command that diagnoses a missing key must not need one."""
    result, _ = run(["doctor"], obj=CredentialsError("no API key found. Set X"))

    assert result.exit_code == 1
    assert "no API key found" in result.output


def test_doctor_flags_kgsearch_separately_from_trends():
    result, _ = run(
        ["doctor"], Response(200, {"regions": []}), Response(403, None)
    )

    assert "PASS  trends api" in result.output
    assert "FAIL  kgsearch" in result.output


def test_other_commands_fail_cleanly_without_a_key():
    result, _ = run(
        ["series", "/m/0cycc", "--geo", "US", "--from", "2025-07"],
        obj=CredentialsError("no API key found"),
    )

    assert result.exit_code == 1
    assert "no API key found" in result.output


# --- entity -----------------------------------------------------------------


def test_entity_find_merges_both_indexes_and_flags_each_source():
    """Acceptance test 6: an ID only the topic index knows must survive."""
    result, _ = run(
        ["entity", "find", "influenza", "--geo", "US"],
        Response(200, kg_body(("/m/087t7g", "Influenza A virus subtype H1N1"))),
        Response(200, topics_body(("/m/0cycc", "Influenza"))),
        Response(200, topics_body()),
    )

    assert "/m/0cycc" in result.output
    assert "trends-topics" in result.output
    assert "/m/087t7g" in result.output
    assert "kgsearch" in result.output


def test_entity_find_marks_candidates_confirmed_by_both_sources():
    result, _ = run(
        ["entity", "find", "vaccine", "--geo", "US", "--json"],
        Response(200, kg_body(("/m/07__7", "Vaccine"))),
        Response(200, topics_body(("/m/07__7", "Vaccine"))),
        Response(200, topics_body()),
    )

    candidates = json.loads(result.output)["candidates"]
    assert candidates[0]["source"] == "kgsearch+trends-topics"


def test_entity_verify_exits_three_on_a_name_mismatch():
    """Acceptance test 7."""
    result, _ = run(
        ["entity", "verify", "/m/07__7", "--is", "Influenza"],
        Response(200, kg_body(("/m/07__7", "Vaccine"))),
    )

    assert result.exit_code == 3
    assert "is currently 'Vaccine'" in result.output


def test_entity_verify_passes_when_the_name_matches():
    result, _ = run(
        ["entity", "verify", "/m/07__7", "--is", "vaccine"],
        Response(200, kg_body(("/m/07__7", "Vaccine"))),
    )

    assert result.exit_code == 0


def test_entity_verify_says_so_when_the_id_is_absent_from_kgsearch():
    """Absence is not proof the ID is wrong, and the message must say so."""
    result, _ = run(
        ["entity", "verify", "/m/0cycc", "--is", "Influenza"],
        Response(200, {"itemListElement": []}),
    )

    assert result.exit_code == 3
    assert "does not mean the ID is wrong" in result.output


def test_entity_coverage_compares_the_entity_against_its_variants():
    """Acceptance test 8."""
    body = {
        "lines": [
            timeline_body(("Jul 01 2025", 100.0), term="/m/0cycc")["lines"][0],
            timeline_body(("Jul 01 2025", 30.0), term="flu")["lines"][0],
            timeline_body(("Jul 01 2025", 20.0), term="grippe")["lines"][0],
        ]
    }

    result, _ = run(
        [
            "entity",
            "coverage",
            "/m/0cycc",
            "--text",
            "flu",
            "--text",
            "grippe",
            "--geo",
            "US",
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-01",
        ],
        Response(200, body),
    )

    assert result.exit_code == 0
    assert "sum of variants" in result.output
    assert "50.0" in result.output  # 30 + 20
    assert "entity find" not in result.output  # --text must not warn


# --- queries and topics -----------------------------------------------------


def test_queries_states_the_month_granularity_limit():
    result, _ = run(
        ["queries", "/m/0cycc", "--geo", "US", "--from", "2025-07"],
        Response(200, {"item": [{"title": "flu shot", "value": 100}]}),
    )

    assert "month granularity is a hard API limit" in result.output
    assert "flu shot" in result.output


def test_queries_refuses_a_sub_month_range_before_calling():
    """Acceptance test 4: the clamp rule applies here identically."""
    result, transport = run(
        [
            "queries",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2026-07-15",
            "--to",
            "2026-07-20",
        ],
    )

    assert result.exit_code == 1
    assert "no whole month" in result.output
    assert transport.calls == []


def test_topics_returns_mids_and_plain_output_feeds_series():
    result, _ = run(
        ["topics", "/m/0cycc", "--geo", "US", "--from", "2025-07", "--plain"],
        Response(
            200, topics_body(("/m/07__7", "Vaccine"), ("/m/0d1p2", "Fever"))
        ),
    )

    assert result.output.split() == ["/m/07__7", "/m/0d1p2"]


def test_vs_diffs_two_periods():
    result, transport = run(
        [
            "queries",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2026-07",
            "--vs",
            "2025-07",
        ],
        Response(200, {"item": [{"title": "now", "value": 100}]}),
        Response(200, {"item": [{"title": "then", "value": 90}]}),
    )

    assert len(transport.calls) == 2
    assert "now" in result.output and "then" in result.output
    assert "comparison period: 2025-07" in result.output


# --- check ------------------------------------------------------------------


def test_check_censoring_reports_runs_as_well_as_percentages():
    result, _ = run(
        [
            "check",
            "censoring",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-04",
            "--json",
        ],
        Response(
            200,
            timeline_body(
                ("Jul 01 2025", 0.0),
                ("Jul 02 2025", 0.0),
                ("Jul 03 2025", 0.0),
                ("Jul 04 2025", 5.0),
            ),
        ),
    )

    stats = json.loads(result.output)
    assert stats["pct_zero"] == 75.0
    assert stats["longest_zero_run"] == 3


def test_check_variance_reports_spread_across_identical_fetches():
    steady = Response(200, timeline_body(("Jul 01 2025", 100.0)))
    moved = Response(200, timeline_body(("Jul 01 2025", 108.0)))

    result, transport = run(
        [
            "check",
            "variance",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-01",
            "--repeat",
            "2",
            "--json",
        ],
        steady,
        moved,
    )

    report = json.loads(result.output)
    assert len(transport.calls) == 2
    assert report["max_spread_pct"] > 7
    assert report["identical"] is False


def test_check_vs_public_compares_shape_not_values():
    result, _ = run(
        [
            "check",
            "vs-public",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07",
            "--to",
            "2025-09",
            "--json",
        ],
        Response(
            200,
            timeline_body(
                ("Jul 2025", 100.0), ("Aug 2025", 200.0), ("Sep 2025", 150.0)
            ),
        ),
        # `graph` labels ISO and picks its own resolution: here it answers a
        # three-month request with daily points, which must still line up.
        Response(
            200,
            {
                "lines": [
                    {
                        "term": "/m/0cycc",
                        "points": [
                            {"date": "2025-07-05", "value": 50},
                            {"date": "2025-07-20", "value": 50},
                            {"date": "2025-08-05", "value": 100},
                            {"date": "2025-09-05", "value": 75},
                        ],
                    }
                ]
            },
        ),
    )

    report = json.loads(result.output)
    assert report["points"] == 3
    assert report["rank_agreement"] == 1.0


def test_entity_find_does_not_rank_by_incomparable_scores():
    """The indexes score on different scales; a popular unrelated topic must
    not outrank the Knowledge Graph's own best match for the query."""
    result, _ = run(
        ["entity", "find", "influenza", "--geo", "US", "--json"],
        Response(200, kg_body(("/m/0cycc", "Influenza"))),
        Response(
            200,
            {
                "item": [
                    {
                        "title": "Encyclopaedia Britannica",
                        "mid": "/m/02ljv",
                        "value": 73750,
                    },
                ]
            },
        ),
        Response(200, topics_body()),
    )

    candidates = json.loads(result.output)["candidates"]
    assert candidates[0]["mid"] == "/m/0cycc"


def test_queries_reports_the_months_a_clamp_dropped():
    """A window trimmed by seven weeks must not vanish silently; `series`
    always reported this and `discover` used to lose it."""
    result, _ = run(
        [
            "queries",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07-15",
            "--to",
            "2025-09-20",
            "--json",
        ],
        Response(200, {"item": [{"title": "flu", "value": 100}]}),
    )

    payload = json.loads(result.output)
    assert payload["meta"]["date_start"] == "2025-08-01"
    assert any("dropped partial leading" in w for w in payload["warnings"])
    assert any("dropped partial trailing" in w for w in payload["warnings"])


def test_check_censoring_on_an_empty_series_is_a_clean_error():
    result, _ = run(
        [
            "check",
            "censoring",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-02",
        ],
        Response(200, {"lines": []}),
    )

    assert result.exit_code == 1
    assert "nothing to characterise" in result.output
    assert "Traceback" not in result.output


def test_vs_public_admits_when_there_is_too_little_to_compare():
    """Reporting 1.0 on a single month would read as perfect agreement."""
    result, _ = run(
        [
            "check",
            "vs-public",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07",
            "--to",
            "2025-07",
            "--json",
        ],
        Response(200, timeline_body(("Jul 2025", 100.0))),
        Response(
            200,
            {
                "lines": [
                    {
                        "term": "x",
                        "points": [{"date": "2025-07-05", "value": 50}],
                    }
                ]
            },
        ),
    )

    report = json.loads(result.output)
    assert report["points"] == 1
    assert report["rank_agreement"] is None


def test_variance_admits_when_nothing_was_compared():
    result, _ = run(
        [
            "check",
            "variance",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-01",
            "--repeat",
            "1",
        ],
        Response(200, timeline_body(("Jul 01 2025", 100.0))),
    )

    assert "nothing was actually compared" in result.output
    assert "agreed exactly" not in result.output


def test_entity_coverage_leaves_the_derived_row_blank_when_unmeasured():
    """A zero there would claim the variants were searched for zero times."""
    result, _ = run(
        [
            "entity",
            "coverage",
            "/m/0cycc",
            "--text",
            "flu",
            "--geo",
            "US",
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-01",
        ],
        Response(200, timeline_body(("Jul 01 2025", 100.0), term="/m/0cycc")),
    )

    assert result.exit_code == 0
    sums = [ln for ln in result.output.splitlines() if "sum of variants" in ln]
    assert sums and "0" not in sums[0].replace("-- sum of variants --", "")


def test_entity_coverage_rejects_a_bad_date_cleanly():
    result, _ = run(
        [
            "entity",
            "coverage",
            "/m/0cycc",
            "--text",
            "flu",
            "--geo",
            "US",
            "--from",
            "garbage",
        ],
    )

    assert result.exit_code == 1
    assert "Traceback" not in result.output


def test_rank_agreement_ignores_tied_pairs():
    """Two identically flat series agree perfectly. Counting ties as
    disagreement reported 0.0 -- on exactly the censored data this tool
    spends its time warning about."""
    assert _rank_agreement([5, 5, 5], [5, 5, 5]) != _rank_agreement(
        [1, 2], [2, 1]
    )
    assert _rank_agreement([0, 0, 0, 1, 2], [0, 0, 0, 10, 20]) == 1.0
    assert _rank_agreement([1, 2, 3], [10, 20, 30]) == 1.0
    assert _rank_agreement([1, 2, 3], [30, 20, 10]) == 0.0


def test_rank_agreement_is_undefined_when_every_pair_is_tied():
    assert math.isnan(_rank_agreement([5, 5, 5], [5, 5, 5]))


def test_variance_json_does_not_claim_identical_from_one_fetch():
    """The human path was guarded; --json is what an agent reads."""
    result, _ = run(
        [
            "check",
            "variance",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-01",
            "--repeat",
            "1",
            "--json",
        ],
        Response(200, timeline_body(("Jul 01 2025", 100.0))),
    )

    report = json.loads(result.output)
    assert report["identical"] is None
    assert report["compared"] is False


def test_an_absurd_repeat_is_refused_before_spending_quota():
    result, transport = run(
        [
            "check",
            "variance",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07-01",
            "--repeat",
            "100000",
        ],
    )

    assert result.exit_code == 1
    assert transport.calls == []


def test_vs_public_reports_the_months_its_clamp_dropped():
    result, _ = run(
        [
            "check",
            "vs-public",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2024-01-15",
            "--to",
            "2024-06-20",
        ],
        Response(200, timeline_body(("Feb 2024", 10.0), ("Mar 2024", 20.0))),
        Response(
            200,
            {
                "lines": [
                    {
                        "term": "x",
                        "points": [
                            {"date": "2024-02-05", "value": 5},
                            {"date": "2024-03-05", "value": 9},
                        ],
                    }
                ]
            },
        ),
    )

    assert "dropped partial" in result.output
    assert "covering: 2024-02-01..2024-05-31" in result.output


def test_queries_refuses_two_output_formats():
    result, _ = run(
        [
            "queries",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07",
            "--json",
            "--plain",
        ],
        Response(200, {"item": []}),
    )

    assert result.exit_code == 1
    assert "one output format" in result.output


def test_a_nonsense_top_is_refused():
    for value in ("-1", "0"):
        result, transport = run(
            [
                "queries",
                "/m/0cycc",
                "--geo",
                "US",
                "--from",
                "2025-07",
                "--top",
                value,
            ],
        )
        assert result.exit_code == 1, value
        assert transport.calls == []


def test_the_comparison_period_is_labelled_with_what_was_fetched():
    """`--vs 2024-03-15` fetches whole months; echoing the raw string back
    claims a window that was never requested of the API."""
    result, _ = run(
        [
            "queries",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07",
            "--vs",
            "2024-03",
        ],
        Response(200, {"item": [{"title": "now", "value": 100}]}),
        Response(200, {"item": [{"title": "then", "value": 90}]}),
    )

    assert "comparison period: 2024-03-01..2024-03-31" in result.output


def test_queries_warns_when_the_api_returns_nothing():
    result, _ = run(
        ["queries", "/m/0cycc", "--geo", "US", "--from", "2025-07", "--json"],
        Response(200, {"item": []}),
    )

    payload = json.loads(result.output)
    assert any("no items" in w for w in payload["warnings"])


# --- guards that a mutation test showed nothing was reaching -----------------


def test_vs_public_refuses_when_the_two_series_share_no_month():
    """Distinct from too-few-points: here there is no overlap at all."""
    result, _ = run(
        [
            "check",
            "vs-public",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07",
            "--to",
            "2025-09",
        ],
        Response(200, timeline_body(("Jul 2025", 10.0), ("Aug 2025", 20.0))),
        Response(
            200,
            {
                "lines": [
                    {
                        "term": "x",
                        "points": [{"date": "2019-01-05", "value": 5}],
                    }
                ]
            },
        ),
    )

    assert result.exit_code == 1
    assert "share no months" in result.output


def test_variance_refuses_an_entirely_empty_response():
    """Distinct from --repeat 1: the fetches worked but returned nothing."""
    result, _ = run(
        [
            "check",
            "variance",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-02",
            "--repeat",
            "2",
        ],
        Response(200, {"lines": []}),
        Response(200, {"lines": []}),
    )

    assert result.exit_code == 1
    assert "no variance to measure" in result.output


def test_variance_does_not_call_runs_identical_when_one_returned_nothing():
    """A run coming back empty is the strongest instability there is; it used
    to be reported as perfect agreement."""
    full = timeline_body(("Jul 01 2025", 10.0), ("Jul 02 2025", 20.0))

    result, _ = run(
        [
            "check",
            "variance",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-02",
            "--repeat",
            "3",
            "--json",
        ],
        Response(200, full),
        Response(200, {"lines": []}),
        Response(200, full),
    )

    report = json.loads(result.output)
    assert report["identical"] is None
    assert report["compared"] is False
    assert report["points"] == 0
    assert report["points_missing_from_some_run"] == 2


def test_variance_flags_dates_missing_from_only_some_runs():
    full = timeline_body(("Jul 01 2025", 10.0), ("Jul 02 2025", 20.0))
    partial = timeline_body(("Jul 01 2025", 10.0))

    result, _ = run(
        [
            "check",
            "variance",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-02",
            "--repeat",
            "2",
        ],
        Response(200, full),
        Response(200, partial),
    )

    assert "absent from at least one run" in result.output
    assert "every run agreed exactly" not in result.output


def test_entity_coverage_refuses_when_nothing_came_back():
    result, _ = run(
        [
            "entity",
            "coverage",
            "/m/0cycc",
            "--text",
            "flu",
            "--geo",
            "US",
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-02",
        ],
        Response(200, {"lines": []}),
    )

    assert result.exit_code == 1
    assert "nothing to compare" in result.output


def test_entity_find_says_when_neither_index_knows_the_name():
    result, _ = run(
        ["entity", "find", "nonesuch", "--geo", "US"],
        Response(200, {"itemListElement": []}),
        Response(200, {"item": []}),
        Response(200, {"item": []}),
    )

    assert result.exit_code == 0
    assert "neither index has an entity" in result.output


def test_entity_verify_json_carries_the_verdict_and_the_exit_code():
    mismatch, _ = run(
        ["entity", "verify", "/m/07__7", "--is", "Influenza", "--json"],
        Response(200, kg_body(("/m/07__7", "Vaccine"))),
    )
    match, _ = run(
        ["entity", "verify", "/m/07__7", "--is", "vaccine", "--json"],
        Response(200, kg_body(("/m/07__7", "Vaccine"))),
    )

    assert mismatch.exit_code == 3
    verdict = json.loads(mismatch.output)
    assert verdict["ok"] is False and verdict["actual"] == "Vaccine"

    assert match.exit_code == 0
    assert json.loads(match.output)["ok"] is True


def test_entity_verify_json_distinguishes_absent_from_mismatched():
    result, _ = run(
        ["entity", "verify", "/m/0cycc", "--is", "Influenza", "--json"],
        Response(200, {"itemListElement": []}),
    )

    verdict = json.loads(result.output)
    assert result.exit_code == 3
    assert verdict["in_knowledge_graph"] is False
    assert verdict["actual"] is None


def test_entity_coverage_json_reports_variants_and_the_entity():
    body = {
        "lines": [
            timeline_body(("Jul 01 2025", 100.0), term="/m/0cycc")["lines"][0],
            timeline_body(("Jul 01 2025", 30.0), term="flu")["lines"][0],
        ]
    }

    result, _ = run(
        [
            "entity",
            "coverage",
            "/m/0cycc",
            "--text",
            "flu",
            "--geo",
            "US",
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-01",
            "--json",
        ],
        Response(200, body),
    )

    payload = json.loads(result.output)
    assert payload["entity"] == "/m/0cycc"
    assert payload["entity_coverage"]["maximum"] == 100.0
    assert [v["term"] for v in payload["variants"]] == ["flu"]
    assert payload["variant_sum_max"] == 30.0


# --- --vs interactions -------------------------------------------------------


def test_vs_warnings_say_which_window_they_belong_to():
    """Unlabelled, a provisional-data warning for a comparison reads as one
    about the primary window, which may be years older."""
    result, _ = run(
        [
            "queries",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2020-07-15",
            "--to",
            "2020-09-20",
            "--vs",
            "2025-07-15",
            "--json",
        ],
        Response(200, {"item": [{"title": "a", "value": 1}]}),
        Response(200, {"item": [{"title": "b", "value": 1}]}),
    )

    warnings = json.loads(result.output)["warnings"]
    assert any(w.startswith("requested window 2020-08-01") for w in warnings)
    assert any(w.startswith("comparison window 2025-08-01") for w in warnings)


def test_plain_with_vs_is_refused_rather_than_spending_the_request():
    result, transport = run(
        [
            "topics",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07",
            "--vs",
            "2024-07",
            "--plain",
        ],
    )

    assert result.exit_code == 1
    assert "cannot show a --vs comparison" in result.output
    assert transport.calls == []


def test_top_applies_to_the_comparison_as_well_as_the_primary_rows():
    many = {"item": [{"title": f"q{n}", "value": 100 - n} for n in range(5)]}

    result, _ = run(
        [
            "queries",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07",
            "--vs",
            "2024-07",
            "--top",
            "2",
            "--json",
        ],
        Response(200, many),
        Response(200, many),
    )

    payload = json.loads(result.output)
    assert len(payload["items"]) == 2
    assert len(payload["comparison"]) == 2
