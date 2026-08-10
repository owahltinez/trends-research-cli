"""`series` grouping, summaries, chunking and output formats."""

import csv
import io
import json
from datetime import date

from click.testing import CliRunner
from fakes import FakeTransport, timeline_body

from gtrendscli.api.client import Client, Response
from gtrendscli.cli import main

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


def test_regions_become_columns_and_need_no_clamping():
    """`regions` honours full dates, so a six-day range is legitimate."""
    result, transport = run(
        [*BASE, "--from", "2025-07-01", "--to", "2025-07-06", "--by", "region"],
        Response(200, regions_body(**{"US-CA": 90, "US-NY": 70})),
    )

    assert result.exit_code == 0
    assert "US-CA" in result.output and "US-NY" in result.output
    sent = dict(transport.calls[0][1])
    assert sent["restrictions.startDate"] == "2025-07-01"


def test_region_grouping_warns_about_the_code_scheme_and_suppression():
    result, _ = run(
        [*BASE, "--from", "2025-07", "--by", "region"],
        Response(200, regions_body(**{"US-CA": 90})),
    )

    assert "ISO-3166-2" in result.output
    assert "below the release threshold" in result.output


def test_an_interval_with_region_grouping_is_refused():
    result, transport = run(
        [*BASE, "--from", "2025-07", "--by", "region", "--interval", "month"],
    )

    assert result.exit_code == 1, "a usage error, not an API error"
    assert transport.calls == []


def test_years_become_columns_and_no_statistic_is_emitted():
    """Acceptance test 9."""
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
            "2024-2025",
        ],
        Response(
            200, timeline_body(("Jul 21 2024", 10.0), ("Jul 22 2024", 11.0))
        ),
        Response(
            200, timeline_body(("Jul 21 2025", 50.0), ("Jul 22 2025", 51.0))
        ),
    )

    assert result.exit_code == 0
    assert "2024" in result.output and "2025" in result.output
    for forbidden in ("p-value", "significant", "t-test"):
        assert forbidden not in result.output.lower()


def test_by_year_without_years_is_a_usage_error():
    result, transport = run([*BASE, "--from", "07-21", "--by", "year"])

    assert result.exit_code == 1, "a usage error, not an API error"
    assert transport.calls == []


def test_a_summary_is_computed_from_the_daily_points():
    """Acceptance test 1: the mean of six days, not the monthly value."""
    result, transport = run(
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

    payload = json.loads(result.output)
    assert payload["records"] == [
        {
            "date_start": "2025-07-21",
            "date_end": "2025-07-23",
            "term": "flu",
            "group": "",
            "value": 20.0,
        }
    ]
    assert dict(transport.calls[0][1])["timelineResolution"] == "day"


def test_a_summary_with_a_coarse_interval_is_refused():
    """It would silently answer a different question."""
    result, transport = run(
        [
            *BASE,
            "--from",
            "2025-07",
            "--summary",
            "mean",
            "--interval",
            "month",
        ],
    )

    assert result.exit_code == 1, "a usage error, not an API error"
    assert transport.calls == []


def test_a_long_range_chunks_and_concatenates():
    """Acceptance test 10."""
    first = timeline_body(("Jan 01 2024", 1.0))
    second = timeline_body(("Jan 01 2025", 2.0))

    result, transport = run(
        [*BASE, "--from", "2024-01-01", "--to", "2025-12-31", "--json"],
        Response(200, first),
        Response(200, second),
    )

    assert len(transport.calls) == 2
    payload = json.loads(result.output)
    assert [r["value"] for r in payload["records"]] == [1.0, 2.0]

    # The chunks must abut exactly. A gap loses days silently; an overlap
    # double-counts them. Only asserting the call count would miss both.
    first, second = (dict(call[1]) for call in transport.calls)
    assert first["time.startDate"] == "2024-01-01"
    assert second["time.endDate"] == "2025-12-31"
    assert (
        date.fromisoformat(second["time.startDate"])
        - date.fromisoformat(first["time.endDate"])
    ).days == 1


def test_a_censored_series_warns_in_both_table_and_json():
    """Acceptance test 11."""
    sparse = timeline_body(
        ("Jul 01 2025", 0.0), ("Jul 02 2025", 0.0), ("Jul 03 2025", 5.0)
    )

    table, _ = run(
        [*BASE, "--from", "2025-07-01", "--to", "2025-07-03"],
        Response(200, sparse),
    )
    as_json, _ = run(
        [*BASE, "--from", "2025-07-01", "--to", "2025-07-03", "--json"],
        Response(200, sparse),
    )

    assert "66.7% zero" in table.output
    assert any("zero" in w for w in json.loads(as_json.output)["warnings"])


def test_strict_turns_warnings_into_exit_four():
    result, _ = run(
        [
            "series",
            "influenza",
            "--geo",
            "US",
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-01",
            "--strict",
        ],
        Response(200, timeline_body(("Jul 01 2025", 10.0))),
    )

    assert result.exit_code == 4


def test_csv_output_is_tidy_and_keeps_the_unit_attached():
    result, _ = run(
        [*BASE, "--from", "2025-07-01", "--to", "2025-07-01", "--csv"],
        Response(200, timeline_body(("Jul 01 2025", 123.4567890123456))),
    )

    body = [
        line for line in result.output.splitlines() if not line.startswith("#")
    ]
    rows = list(csv.DictReader(io.StringIO("\n".join(body))))

    assert "10,000,000" in result.output
    assert rows[0]["value"] == "123.4567890123456"


def test_plain_output_is_bare_values():
    result, _ = run(
        [*BASE, "--from", "2025-07-01", "--to", "2025-07-02", "--plain"],
        Response(
            200, timeline_body(("Jul 01 2025", 10.0), ("Jul 02 2025", 20.0))
        ),
    )

    assert result.output.split() == ["10.0", "20.0"]


def test_a_receipt_records_every_call_but_never_the_key(tmp_path):
    receipt = tmp_path / "receipt.json"

    run(
        [
            *BASE,
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-01",
            "--receipt",
            str(receipt),
        ],
        Response(200, timeline_body(("Jul 01 2025", 10.0))),
    )

    written = json.loads(receipt.read_text())
    assert len(written["calls"]) == 1
    assert written["calls"][0]["endpoint"] == "timelinesForHealth"
    assert "key" not in receipt.read_text().lower().replace('"endpoint"', "")


def test_a_missing_parquet_extra_reports_cleanly(tmp_path, monkeypatch):
    """A missing optional dependency is a setup problem, not a traceback."""

    def unavailable(_result, _path):
        raise RuntimeError("parquet output needs the optional extra")

    monkeypatch.setattr("gtrendscli.output.options.write_parquet", unavailable)

    result, _ = run(
        [
            *BASE,
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-01",
            "--parquet",
            str(tmp_path / "x.parquet"),
        ],
        Response(200, timeline_body(("Jul 01 2025", 10.0))),
    )

    assert result.exit_code == 1
    assert "optional extra" in result.output
    assert "Traceback" not in result.output


def test_a_missing_required_option_also_exits_one(monkeypatch):
    """Click's own usage errors must use the documented code too, or an agent
    reads a forgotten flag as a transient API failure and retries it."""
    result, _ = run(["series", "/m/0cycc"])

    assert result.exit_code == 1
    assert "Missing option" in result.output or "Usage" in result.output


def test_too_many_terms_is_a_clean_error_not_a_traceback():
    result, transport = run(
        [
            "series",
            *[f"/m/{n}" for n in range(31)],
            "--geo",
            "US",
            "--from",
            "2025-07",
        ],
    )

    assert result.exit_code == 1
    assert "30" in result.output
    assert "Traceback" not in result.output
    assert transport.calls == []


def test_an_empty_response_warns_rather_than_looking_like_success():
    """'The API returned nothing' must not read the same as 'I asked for
    nothing'."""
    result, _ = run(
        [*BASE, "--from", "2025-07-01", "--to", "2025-07-02", "--json"],
        Response(200, {"lines": []}),
    )

    payload = json.loads(result.output)
    assert payload["records"] == []
    assert any("no data points" in w for w in payload["warnings"])


def test_years_given_out_of_order_still_produce_a_forward_span():
    """`--years 2026,2024` is legitimate; a backwards covered span would
    silence the freshness check and mislabel every summary."""
    result, _ = run(
        [
            *BASE,
            "--from",
            "07-21",
            "--to",
            "07-21",
            "--by",
            "year",
            "--years",
            "2026,2024",
            "--json",
        ],
        Response(200, timeline_body(("Jul 21 2026", 10.0))),
        Response(200, timeline_body(("Jul 21 2024", 20.0))),
    )

    meta = json.loads(result.output)["meta"]
    assert meta["date_start"] <= meta["date_end"]
    assert meta["date_start"].startswith("2024")


def test_parquet_carries_the_warnings_and_says_where_it_wrote(tmp_path):
    """A silent exit 0 on a censored series is the failure this tool exists
    to prevent, so writing a file must not swallow the caveats."""
    pyarrow = __import__("pyarrow.parquet", fromlist=["parquet"])
    target = tmp_path / "out.parquet"

    result, _ = run(
        [
            *BASE,
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-03",
            "--parquet",
            str(target),
        ],
        Response(
            200,
            timeline_body(
                ("Jul 01 2025", 0.0), ("Jul 02 2025", 0.0), ("Jul 03 2025", 5.0)
            ),
        ),
    )

    assert result.exit_code == 0
    assert "warning" in result.output, "warnings must reach the terminal too"

    metadata = pyarrow.read_table(target).schema.metadata
    warnings = json.loads(metadata[b"warnings"])
    assert any("zero" in w for w in warnings)


def test_two_output_formats_at_once_is_refused():
    """Picking one silently hands a pipeline a format it did not ask for."""
    result, _ = run(
        [
            *BASE,
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-01",
            "--json",
            "--csv",
        ],
        Response(200, timeline_body(("Jul 01 2025", 10.0))),
    )

    assert result.exit_code == 1
    assert "one output format" in result.output


def test_by_year_reports_the_span_it_actually_fetched():
    """A clamp is reported honestly on --by date; it must be here too."""
    result, transport = run(
        [
            *BASE,
            "--from",
            "01-01",
            "--to",
            "02-20",
            "--by",
            "year",
            "--years",
            "2025",
            "--interval",
            "month",
            "--json",
        ],
        Response(200, timeline_body(("Jan 2025", 10.0))),
    )

    meta = json.loads(result.output)["meta"]
    assert meta["date_end"] == "2025-01-31", "not the unclamped 2025-02-20"
    assert dict(transport.calls[0][1])["time.endDate"] == "2025-01-31"


def test_a_newline_in_a_geo_is_refused_before_anything_is_fetched():
    """First line of defence. A reader stripping `#` lines would take a forged
    line as data, and no real geo code contains a control character."""
    result, transport = run(
        [
            "series",
            "/m/0cycc",
            "--geo",
            "US\n1999-01-01,1999-01-01,forged,,99999",
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-01",
            "--csv",
        ],
    )

    assert result.exit_code == 1
    assert "control character" in result.output
    assert transport.calls == [], "refused before a request was spent"


def test_an_unwritable_receipt_does_not_discard_the_data(tmp_path):
    """The quota is already spent; losing the answer over a receipt would be
    a worse trade than losing the receipt."""
    result, _ = run(
        [
            *BASE,
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-01",
            "--json",
            "--receipt",
            str(tmp_path / "no" / "such" / "dir" / "r.json"),
        ],
        Response(200, timeline_body(("Jul 01 2025", 10.0))),
    )

    assert result.exit_code == 0
    assert "could not write receipt" in result.output

    # The warning goes to stderr, which the runner mixes in; the data is still
    # on stdout ahead of it.
    payload = result.output[: result.output.index("# warning:")]
    assert json.loads(payload)["records"][0]["value"] == 10.0


def test_the_raw_archive_never_overwrites_a_previous_run(tmp_path):
    """Losing the earlier evidence without a word defeats the point of it."""
    for value in (1.0, 2.0):
        transport = FakeTransport(
            Response(200, timeline_body(("Jul 01 2025", value)))
        )
        client = Client(transport, sleep=lambda _: None, raw_dir=tmp_path)
        RUNNER.invoke(
            main,
            [*BASE, "--from", "2025-07-01", "--to", "2025-07-01"],
            obj=client,
        )

    archives = sorted(tmp_path.glob("*.json"))
    assert len(archives) == 2, "the first run's archive must survive the second"
