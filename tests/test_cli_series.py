"""The `series` command end to end, against a fake transport."""

import json

from click.testing import CliRunner
from fakes import FakeTransport, timeline_body

from gtrendscli.api.client import Client, Response
from gtrendscli.cli import main

RUNNER = CliRunner()


def run(args, *responses):
    transport = FakeTransport(*responses)
    client = Client(transport, sleep=lambda _: None)
    return RUNNER.invoke(main, args, obj=client), transport


DAILY = Response(
    200, timeline_body(("Jul 01 2025", 152.8), ("Jul 02 2025", 129.4))
)


def test_a_daily_series_prints_a_dated_table():
    result, _ = run(
        [
            "series",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-02",
        ],
        DAILY,
    )

    assert result.exit_code == 0
    assert "2025-07-01" in result.output
    assert "152.8" in result.output


def test_the_header_states_the_unit_geo_interval_and_endpoint():
    """A reader who cannot see the unit cannot check the number."""
    result, _ = run(
        [
            "series",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-02",
        ],
        DAILY,
    )

    assert "10,000,000" in result.output
    assert "US" in result.output
    assert "timelinesForHealth" in result.output


def test_free_text_warns_and_suggests_finding_an_entity():
    result, _ = run(
        [
            "series",
            "influenza",
            "--geo",
            "US",
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-02",
        ],
        DAILY,
    )

    assert result.exit_code == 0
    assert "entity find" in result.output


def test_an_entity_id_does_not_warn():
    result, _ = run(
        [
            "series",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-02",
        ],
        DAILY,
    )

    assert "entity find" not in result.output


def test_a_month_interval_over_a_short_range_exits_one():
    """Acceptance test 2, now at the command level."""
    result, transport = run(
        [
            "series",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07-21",
            "--to",
            "2025-07-26",
            "--interval",
            "month",
        ],
    )

    assert result.exit_code == 1
    assert "no whole month" in result.output
    assert transport.calls == [], "it must fail before spending a request"


def test_json_output_is_tidy_long_format():
    result, _ = run(
        [
            "series",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-02",
            "--json",
        ],
        DAILY,
    )

    payload = json.loads(result.output)
    assert payload["records"][0] == {
        "date_start": "2025-07-01",
        "date_end": "2025-07-01",
        "term": "flu",
        "group": "",
        "value": 152.8,
    }


def test_json_carries_the_warnings_too():
    """An agent must see this in the output, not infer it from prose."""
    result, _ = run(
        [
            "series",
            "influenza",
            "--geo",
            "US",
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-02",
            "--json",
        ],
        DAILY,
    )

    payload = json.loads(result.output)
    assert any("free text" in w.lower() for w in payload["warnings"])


def test_json_values_are_not_rounded():
    """Acceptance test 15: machine output equals the API response exactly."""
    result, _ = run(
        [
            "series",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07-01",
            "--to",
            "2025-07-01",
            "--json",
        ],
        Response(200, timeline_body(("Jul 01 2025", 123.4567890123456))),
    )

    payload = json.loads(result.output)
    assert payload["records"][0]["value"] == 123.4567890123456


def test_a_clamped_coarse_request_reports_what_was_dropped():
    """Acceptance test 3 at the command level."""
    result, _ = run(
        [
            "series",
            "/m/0cycc",
            "--geo",
            "US",
            "--from",
            "2025-07-15",
            "--to",
            "2025-09-20",
            "--interval",
            "month",
        ],
        Response(200, timeline_body(("Aug 2025", 4000.5))),
    )

    assert result.exit_code == 0
    assert "dropped" in result.output.lower()
    assert "2025-07-15" in result.output and "2025-09-20" in result.output


def test_an_api_failure_exits_two_with_a_diagnosis():
    result, _ = run(
        ["series", "/m/0cycc", "--geo", "US", "--from", "2025-07-01"],
        Response(400, None),
    )

    assert result.exit_code == 2
    assert "parameter" in result.output
