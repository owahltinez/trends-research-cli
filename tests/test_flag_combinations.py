"""Flags that are each correct alone but wrong together.

Every behavioural defect the third review found lived here: `--plain` with
warnings, `--vs` with `--plain`, `--strict` with `--receipt`, `--strict` with
`--by region`, `--summary` with `--by`. Flags were tested individually and
their pairs were not, so this file tests pairs.
"""

import json

from click.testing import CliRunner
from fakes import FakeTransport, timeline_body

from gtrendscli.api.client import Client, Response
from gtrendscli.cli import main

RUNNER = CliRunner()

BASE = ["series", "/m/0cycc", "--geo", "US"]
SPARSE = timeline_body(
    ("Jul 01 2025", 0.0), ("Jul 02 2025", 0.0), ("Jul 03 2025", 5.0)
)
THREE_DAYS = ["--from", "2025-07-01", "--to", "2025-07-03"]


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


# --- --plain must not be the one mode that hides caveats ---------------------


def test_plain_still_reports_a_censored_series():
    """stdout stays bare for piping; the caveat goes to stderr, not nowhere."""
    result, _ = run([*BASE, *THREE_DAYS, "--plain"], Response(200, SPARSE))

    assert result.exit_code == 0
    assert "0.0\n0.0\n5.0" in result.output, "the values still pipe cleanly"
    assert "66.7% zero" in result.output


def test_plain_still_reports_a_clamped_window():
    result, _ = run(
        [
            *BASE,
            "--from",
            "2025-07-15",
            "--to",
            "2025-09-20",
            "--interval",
            "month",
            "--plain",
        ],
        Response(200, timeline_body(("Aug 2025", 10.0))),
    )

    assert "dropped partial" in result.output


def test_plain_output_itself_stays_free_of_commentary(capsys):
    """A pipeline consuming stdout must see numbers only."""
    result, _ = run([*BASE, *THREE_DAYS, "--plain"], Response(200, SPARSE))

    values = [
        line for line in result.output.splitlines() if not line.startswith("#")
    ]
    assert values == ["0.0", "0.0", "5.0"]


# --- --strict must fire on real problems and only on real problems ----------


def test_strict_does_not_fail_on_flawless_region_data():
    """The boilerplate region caveats are notes, not warnings; counting them
    made --strict useless with --by region."""
    result, _ = run(
        [*BASE, "--from", "2025-07", "--by", "region", "--strict"],
        Response(200, regions_body(**{"US-CA": 90, "US-NY": 70})),
    )

    assert result.exit_code == 0
    assert "ISO-3166-2" in result.output, "the caveats are still shown"


def test_region_notes_appear_in_json_as_notes_not_warnings():
    result, _ = run(
        [*BASE, "--from", "2025-07", "--by", "region", "--json"],
        Response(200, regions_body(**{"US-CA": 90})),
    )

    payload = json.loads(result.output)
    assert any("ISO-3166-2" in note for note in payload["notes"])
    assert not any("ISO-3166-2" in w for w in payload["warnings"])


def test_zero_regions_get_one_aggregate_warning_not_one_each():
    """The percent-zero threshold means nothing applied to a single value."""
    result, _ = run(
        [*BASE, "--from", "2025-07", "--by", "region", "--json"],
        Response(200, regions_body(**{"US-CA": 90, "US-WY": 0, "US-VT": 0})),
    )

    warnings = json.loads(result.output)["warnings"]
    zero_warnings = [w for w in warnings if "zero" in w]
    assert len(zero_warnings) == 1
    assert "2 of 3 regions are zero" in zero_warnings[0]
    assert "US-VT, US-WY" in zero_warnings[0]


def test_strict_escalates_a_receipt_that_could_not_be_written(tmp_path):
    """Asking for provenance and strictness must not yield neither."""
    result, _ = run(
        [
            *BASE,
            *THREE_DAYS,
            "--strict",
            "--receipt",
            str(tmp_path / "no" / "dir" / "r.json"),
        ],
        Response(200, timeline_body(("Jul 01 2025", 10.0))),
    )

    assert result.exit_code == 4
    assert "could not write receipt" in result.output


# --- --summary interacts with --by --------------------------------------------


def test_summary_by_year_stamps_each_year_with_its_own_span():
    """One requested window covers every year at once; stamping it on each
    year's mean claims a coverage no value has."""
    result, _ = run(
        [
            *BASE,
            "--from",
            "07-21",
            "--to",
            "07-22",
            "--by",
            "year",
            "--years",
            "2023-2025",
            "--summary",
            "mean",
            "--json",
        ],
        Response(
            200, timeline_body(("Jul 21 2023", 1.0), ("Jul 22 2023", 2.0))
        ),
        Response(
            200, timeline_body(("Jul 21 2024", 3.0), ("Jul 22 2024", 4.0))
        ),
        Response(
            200, timeline_body(("Jul 21 2025", 5.0), ("Jul 22 2025", 6.0))
        ),
    )

    spans = {
        record["group"]: (record["date_start"], record["date_end"])
        for record in json.loads(result.output)["records"]
    }
    assert spans["2023"] == ("2023-07-21", "2023-07-22")
    assert spans["2024"] == ("2024-07-21", "2024-07-22")
    assert spans["2025"] == ("2025-07-21", "2025-07-22")


def test_summary_by_date_still_spans_the_dates_requested():
    """Acceptance test 1 must survive the per-group span change."""
    result, _ = run(
        [
            *BASE,
            "--from",
            "2025-07-21",
            "--to",
            "2025-07-23",
            "--summary",
            "mean",
            "--json",
        ],
        Response(
            200,
            timeline_body(
                ("Jul 21 2025", 10.0),
                ("Jul 22 2025", 20.0),
                ("Jul 23 2025", 30.0),
            ),
        ),
    )

    record = json.loads(result.output)["records"][0]
    assert (record["date_start"], record["date_end"]) == (
        "2025-07-21",
        "2025-07-23",
    )
    assert record["value"] == 20.0


def test_summary_with_several_terms_summarises_each_separately():
    body = {
        "lines": [
            timeline_body(
                ("Jul 01 2025", 10.0), ("Jul 02 2025", 20.0), term="flu"
            )["lines"][0],
            timeline_body(
                ("Jul 01 2025", 100.0), ("Jul 02 2025", 200.0), term="vaccine"
            )["lines"][0],
        ]
    }

    result, _ = run(
        [
            *BASE,
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-02",
            "--summary",
            "mean",
            "--json",
        ],
        Response(200, body),
    )

    values = {
        r["term"]: r["value"] for r in json.loads(result.output)["records"]
    }
    assert values == {"flu": 15.0, "vaccine": 150.0}


def test_summary_with_region_grouping_is_refused():
    """One value per region is already a summary; collapsing it is a no-op."""
    result, transport = run(
        [*BASE, "--from", "2025-07", "--by", "region", "--summary", "mean"],
    )

    assert result.exit_code == 1
    assert transport.calls == []


# --- --years costs one request per year --------------------------------------


def test_an_absurd_year_range_is_refused_before_spending_quota():
    result, transport = run(
        [
            *BASE,
            "--from",
            "07-01",
            "--to",
            "07-02",
            "--by",
            "year",
            "--years",
            "1900-2100",
        ],
    )

    assert result.exit_code == 1
    assert "separate request" in result.output
    assert transport.calls == []
