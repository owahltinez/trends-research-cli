"""`gtrends entity` — am I measuring the right thing?."""

from __future__ import annotations

import json
from datetime import date, timedelta

import click

from trends_research_cli import helptext
from trends_research_cli.api.kgsearch import lookup
from trends_research_cli.dates import (
    ClampError,
    DateFormatError,
    DateRange,
    Interval,
    clamp,
    parse_range,
    today_utc,
)
from trends_research_cli.entities import find
from trends_research_cli.exits import AssertionFailure, guard_api
from trends_research_cli.fetching import fetch_timelines
from trends_research_cli.output.table import Table, format_value, render
from trends_research_cli.quality import coverage
from trends_research_cli.session import require_client

LOOKBACK_DAYS = 365


def _default_span() -> DateRange:
    """A recent year, since the topic index needs some window to search."""
    today = today_utc()
    return DateRange(today - timedelta(days=LOOKBACK_DAYS), today)


@click.group()
def entity() -> None:
    """Find, verify and sanity-check entity IDs."""


@entity.command(
    "find",
    epilog='Example:\n\n  gtrends entity find "influenza" --geo US --plain',
)
@click.argument("query")
@click.option(
    "--geo",
    default="US",
    show_default=True,
    help="Geo whose topic index to search. " + helptext.GEO,
)
@click.option(
    "--json", "as_json", is_flag=True, help="Machine-readable output."
)
@click.option(
    "--plain", "as_plain", is_flag=True, help="Bare MIDs, one per line."
)
@click.pass_obj
def find_command(
    obj, query: str, geo: str, as_json: bool, as_plain: bool
) -> None:
    """Find entity IDs for a name, from both available indexes.

    Both are consulted because neither is complete: entities Trends serves data
    for are routinely missing from the Knowledge Graph, and vice versa.
    """
    client = require_client(obj)
    span = _default_span()

    try:
        candidates = find(client, query, geo=geo, span=span)
    except Exception as exc:
        raise guard_api(exc) from exc

    if not candidates:
        click.echo(
            f"# warning: neither index has an entity for {query!r} in {geo}. "
            f"Try a different spelling, a broader geo, or the local-language "
            f"name; searching free text instead will match strings, not the "
            f"concept.",
            err=True,
        )

    if as_plain:
        click.echo("\n".join(candidate.mid for candidate in candidates))
        return

    if as_json:
        click.echo(
            json.dumps(
                {
                    "query": query,
                    "geo": geo,
                    "candidates": [vars(c) for c in candidates],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    click.echo(f"# entity candidates for {query!r} in {geo}")
    click.echo(
        "# ordered: confirmed by both indexes first, then Knowledge Graph "
        "relevance, then the topic index"
    )
    click.echo(
        "# no score column: the two indexes score on incomparable scales"
    )
    click.echo(
        render(
            Table(
                columns=["mid", "name", "source"],
                rows=[[c.mid, c.name, c.source] for c in candidates],
                pivoted=True,
            )
        )
    )


@entity.command(
    "verify",
    epilog='Example:\n\n  gtrends entity verify /m/07__7 --is "Vaccine"\n\n'
    "Exits 3 if the name differs or cannot be confirmed.",
)
@click.argument("mid")
@click.option(
    "--is",
    "expected",
    required=True,
    help="The name you expect this ID to have. Exit 3 if it does not.",
)
@click.option("--json", "as_json", is_flag=True, help=helptext.JSON)
@click.pass_obj
def verify_command(obj, mid: str, expected: str, as_json: bool) -> None:
    """Check that an ID still names what you think it does.

    An upstream ID can repoint and silently change what a series measures, so
    this is worth running before a collection rather than after.

    Exits 3 on a mismatch, and also when the ID is absent from the Knowledge
    Graph: you asked for an assertion, and an unverifiable ID has not met it.
    Absence is not proof the ID is wrong -- many working MIDs are missing from
    that index -- so the message says which case occurred.
    """
    client = require_client(obj)

    try:
        candidate = lookup(client, mid)
    except Exception as exc:
        raise guard_api(exc) from exc

    actual = candidate.name if candidate else None
    verdict = {
        "mid": mid,
        "expected": expected,
        "actual": actual,
        "ok": actual is not None and actual.casefold() == expected.casefold(),
        "in_knowledge_graph": candidate is not None,
    }

    # The exit code carries the verdict, but an agent reading structured
    # output should not have to infer the reason from it.
    if as_json:
        click.echo(json.dumps(verdict, indent=2, ensure_ascii=False))
        if not verdict["ok"]:
            raise click.exceptions.Exit(AssertionFailure.exit_code)
        return

    if candidate is None:
        raise AssertionFailure(
            f"{mid} is not in the Knowledge Graph, so its name cannot be "
            f"verified. This does not mean the ID is wrong: Trends serves data "
            f"for IDs missing from that index. Cross-check with "
            f"`gtrends entity find {expected!r}`."
        )

    if candidate.name.casefold() != expected.casefold():
        raise AssertionFailure(
            f"{mid} is currently {candidate.name!r}, not {expected!r}. "
            f"Anything measured with this ID is measuring {candidate.name!r}."
        )

    click.echo(f"{mid} is {candidate.name!r}, as expected")


@entity.command(
    "coverage",
    epilog="Example:\n\n  gtrends entity coverage /m/0cycc "
    "--text flu --text grippe \\\n      --geo US --from 2025-07",
)
@click.argument("mid")
@click.option(
    "--text",
    "texts",
    multiple=True,
    required=True,
    help=(
        "A free-text variant to compare against. Repeat the flag per variant "
        "rather than passing a delimited list; non-Latin scripts welcome."
    ),
)
@click.option("--geo", required=True, help=helptext.GEO)
@click.option("--from", "date_from", required=True, help=helptext.DATE_FROM)
@click.option("--to", "date_to", help=helptext.DATE_TO)
@click.option("--json", "as_json", is_flag=True, help=helptext.JSON)
@click.pass_obj
def coverage_command(
    obj,
    mid: str,
    texts: tuple[str, ...],
    geo: str,
    date_from: str,
    date_to: str | None,
    as_json: bool,
) -> None:
    """Does this entity capture the words people actually type?

    Fetches the entity and each variant over the same window. An entity well
    above the sum of its variants is evidence topic aggregation is working;
    below it means the ID is missing spellings.

    `--text` values are exempt from the free-text warning: free text is the
    entire point here.
    """
    client = require_client(obj)
    variants = list(dict.fromkeys(texts))

    if len(variants) != len(texts):
        click.echo("# note: duplicate --text values were ignored", err=True)

    try:
        span = parse_range(date_from, date_to, today=today_utc())
        records = fetch_timelines(
            client,
            terms=[mid, *variants],
            geo=geo,
            periods=clamp(span, Interval.DAY).periods,
            interval=Interval.DAY,
        )
    except (DateFormatError, ClampError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:
        raise guard_api(exc) from exc

    if not records:
        raise click.ClickException(
            f"the API returned no data for {mid} or its variants in {geo} over "
            f"{span.start}..{span.end}, so there is nothing to compare"
        )

    by_term = {stats.term: stats for stats in coverage(records)}

    if as_json:
        totals = _variant_totals(records, variants)
        click.echo(
            json.dumps(
                {
                    "entity": mid,
                    "geo": geo,
                    "date_start": span.start.isoformat(),
                    "date_end": span.end.isoformat(),
                    "variants": [
                        vars(by_term[v]) for v in variants if v in by_term
                    ],
                    "entity_coverage": (
                        vars(by_term[mid]) if mid in by_term else None
                    ),
                    "variant_sum_median": totals[0] if totals else None,
                    "variant_sum_max": totals[1] if totals else None,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    rows = []

    for variant in variants:
        stats = by_term.get(variant)
        rows.append(
            [
                variant,
                "text",
                f"{stats.pct_zero:.1f}" if stats else "",
                format_value(stats.median) if stats else "",
                format_value(stats.maximum) if stats else "",
            ]
        )

    # The two derived rows are the point of the command, so compute them here
    # rather than leaving the reader to add up columns.
    totals = _variant_totals(records, variants)
    rows.append(
        [
            "-- sum of variants --",
            "",
            "",
            format_value(totals[0]) if totals else "",
            format_value(totals[1]) if totals else "",
        ]
    )

    entity_stats = by_term.get(mid)
    rows.append(
        [
            mid,
            "entity",
            f"{entity_stats.pct_zero:.1f}" if entity_stats else "",
            format_value(entity_stats.median) if entity_stats else "",
            format_value(entity_stats.maximum) if entity_stats else "",
        ]
    )

    click.echo(
        f"# coverage of {mid} against {len(variants)} free-text variants"
    )
    click.echo(f"# geo: {geo}  covering: {span.start}..{span.end}")
    click.echo(
        render(
            Table(
                columns=["term", "source", "pct_zero", "median", "max"],
                rows=rows,
                pivoted=True,
            )
        )
    )


def _variant_totals(records, variants: list[str]) -> tuple[float, float] | None:
    """Sum the variants per day, then summarise that combined series.

    Returns None when no variant data came back at all: a zero there would say
    "the variants were searched for zero times" when the truth is that they
    were never measured, which is the exact ambiguity this tool refuses to
    manufacture.
    """
    per_day: dict[date, float] = {}

    for record in records:
        if record.term in variants:
            per_day[record.date_start] = (
                per_day.get(record.date_start, 0.0) + record.value
            )

    if not per_day:
        return None

    values = sorted(per_day.values())
    middle = len(values) // 2
    median = (
        values[middle]
        if len(values) % 2
        else (values[middle - 1] + values[middle]) / 2
    )
    return median, max(values)
