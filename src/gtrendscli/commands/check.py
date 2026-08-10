"""`gtrends check` — can I trust this data?."""

from __future__ import annotations

import json
import math
import statistics
from datetime import date

import click

from gtrendscli import helptext
from gtrendscli.api.endpoints import Endpoint, build_params
from gtrendscli.api.parse import parse_index_points
from gtrendscli.dates import (
    ClampError,
    DateFormatError,
    DateRange,
    Interval,
    clamp,
    parse_range,
    today_utc,
)
from gtrendscli.exits import guard_api
from gtrendscli.fetching import fetch_timelines
from gtrendscli.output.table import Table, format_value, render
from gtrendscli.quality import clamp_warnings, coverage
from gtrendscli.session import require_client


@click.group()
def check() -> None:
    """Diagnostics: censoring, sampling variance, and public-index agreement."""


def _span(date_from: str, date_to: str | None) -> DateRange:
    return parse_range(date_from, date_to, today=today_utc())


def _fetch_daily(client, term: str, geo: str, span: DateRange):
    return fetch_timelines(
        client,
        terms=[term],
        geo=geo,
        periods=clamp(span, Interval.DAY).periods,
        interval=Interval.DAY,
    )


@check.command(
    "censoring",
    epilog="Example:\n\n  gtrends check censoring /m/0cycc --geo US "
    "--from 2025-01 --to 2025-12",
)
@click.argument("term")
@click.option("--geo", required=True, help=helptext.GEO)
@click.option("--from", "date_from", required=True, help=helptext.DATE_FROM)
@click.option("--to", "date_to", help=helptext.DATE_TO)
@click.option("--json", "as_json", is_flag=True, help=helptext.JSON)
@click.pass_obj
def censoring(obj, term, geo, date_from, date_to, as_json):
    """How much of this series is zero, and how it is distributed.

    Scattered zeros and one long flat stretch mean different things, so the
    longest run is reported alongside the percentage.
    """
    client = require_client(obj)

    try:
        span = _span(date_from, date_to)
        records = _fetch_daily(client, term, geo, span)
    except (DateFormatError, ClampError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:
        raise guard_api(exc) from exc

    summaries = coverage(records)
    if not summaries:
        raise click.ClickException(
            f"the API returned no data points for {term} in {geo} over "
            f"{span.start}..{span.end}, so there is nothing to characterise"
        )

    stats = summaries[0]

    if as_json:
        click.echo(json.dumps(vars(stats) | {"geo": geo}, indent=2))
        return

    click.echo(f"# censoring of {term} in {geo}, {span.start}..{span.end}")
    click.echo("# a zero means no activity OR too few queries to release")
    click.echo(
        render(
            Table(
                columns=[
                    "points",
                    "zeros",
                    "pct_zero",
                    "longest_run",
                    "median",
                    "max",
                ],
                rows=[
                    [
                        str(stats.count),
                        str(stats.zero_count),
                        format_value(stats.pct_zero),
                        str(stats.longest_zero_run),
                        format_value(stats.median),
                        format_value(stats.maximum),
                    ]
                ],
                pivoted=True,
            )
        )
    )


@check.command(
    "variance",
    epilog="Example:\n\n  gtrends check variance /m/0cycc --geo US "
    "--from 2025-07-01 --to 2025-07-07 --repeat 3",
)
@click.argument("term")
@click.option("--geo", required=True, help=helptext.GEO)
@click.option("--from", "date_from", required=True, help=helptext.DATE_FROM)
@click.option("--to", "date_to", help=helptext.DATE_TO)
@click.option(
    "--repeat",
    default=3,
    show_default=True,
    type=click.IntRange(1, 20),
    help="How many identical fetches to compare. Each one costs quota.",
)
@click.option("--json", "as_json", is_flag=True, help=helptext.JSON)
@click.pass_obj
def variance(obj, term, geo, date_from, date_to, repeat, as_json):
    """Re-fetch an identical window and report how much the numbers move.

    The API is a sampled product: the same query need not return the same
    values tomorrow, so a difference between two runs is not necessarily a
    change in the world.
    """
    client = require_client(obj)

    try:
        span = _span(date_from, date_to)
        runs = [_fetch_daily(client, term, geo, span) for _ in range(repeat)]
    except (DateFormatError, ClampError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:
        raise guard_api(exc) from exc

    # Compare like with like: the same date across runs. A date only some
    # runs returned cannot be compared, and counting it as a zero spread would
    # report perfect agreement for the strongest instability there is -- a run
    # that came back empty.
    by_date: dict[date, list[float]] = {}
    for records in runs:
        for record in records:
            by_date.setdefault(record.date_start, []).append(record.value)

    comparable = {
        day: values for day, values in by_date.items() if len(values) == repeat
    }
    missing = len(by_date) - len(comparable)

    spreads = [
        100.0 * (max(values) - min(values)) / max(values)
        for values in comparable.values()
        if max(values) > 0
    ]
    worst = max(spreads, default=0.0)

    # Only a run-to-run comparison over identical dates can support a verdict.
    settled = repeat > 1 and bool(comparable) and missing == 0

    if not by_date:
        raise click.ClickException(
            f"the API returned no data points for {term} in {geo} over "
            f"{span.start}..{span.end}, so there is no variance to measure"
        )

    if as_json:
        click.echo(
            json.dumps(
                {
                    "repeat": repeat,
                    "points": len(comparable),
                    "points_missing_from_some_run": missing,
                    "max_spread_pct": worst,
                    "median_spread_pct": statistics.median(spreads or [0.0]),
                    # "identical" is a claim about a comparison. Without one
                    # -- a single fetch, or runs that disagree about which
                    # dates exist -- there is nothing to claim.
                    "identical": worst == 0.0 if settled else None,
                    "compared": settled,
                },
                indent=2,
            )
        )
        return

    click.echo(f"# variance of {term} in {geo} over {repeat} identical fetches")
    click.echo(f"# points compared: {len(comparable)}")
    click.echo(f"# largest spread on any one day: {worst:.2f}%")
    click.echo(f"# median spread: {statistics.median(spreads or [0.0]):.2f}%")

    if missing:
        click.echo(
            f"# warning: {missing} date(s) were absent from at least one run, "
            f"so they could not be compared. A run returning different dates "
            f"is itself instability."
        )

    if repeat < 2:
        click.echo(
            "# --repeat was less than 2, so nothing was actually compared"
        )
    elif not comparable:
        click.echo("# no date was returned by every run; nothing was compared")
    elif settled and worst == 0.0:
        click.echo("# every run agreed exactly")


@check.command(
    "vs-public",
    epilog="Example:\n\n  gtrends check vs-public /m/0cycc --geo US "
    "--from 2024-01 --to 2025-12",
)
@click.argument("term")
@click.option("--geo", required=True, help=helptext.GEO)
@click.option("--from", "date_from", required=True, help=helptext.DATE_FROM)
@click.option("--to", "date_to", help=helptext.DATE_TO)
@click.option("--json", "as_json", is_flag=True, help=helptext.JSON)
@click.pass_obj
def vs_public(obj, term, geo, date_from, date_to, as_json):
    """Compare the absolute series against the public 0-100 index.

    Answers "why doesn't this match trends.google.com?". The two should have
    the same *shape*; they cannot have the same values, because the public
    index renormalises to its own maximum on every request. This is the only
    sanctioned use of the `graph` endpoint.
    """
    client = require_client(obj)

    try:
        span = _span(date_from, date_to)
        months = clamp(span, Interval.MONTH)
        covered = DateRange(months.periods[0].start, months.periods[-1].end)

        absolute = fetch_timelines(
            client,
            terms=[term],
            geo=geo,
            periods=months.periods,
            interval=Interval.MONTH,
        )
        indexed = parse_index_points(
            client.fetch(
                Endpoint.GRAPH,
                build_params(
                    Endpoint.GRAPH, terms=[term], geo=geo, span=covered
                ),
            )
        )
    except (DateFormatError, ClampError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:
        raise guard_api(exc) from exc

    for warning in clamp_warnings(months):
        click.echo(f"# warning: {warning}", err=True)

    paired = _pair_by_month(absolute, indexed)

    if not paired:
        raise click.ClickException(
            f"the two series share no months over {covered.start}.."
            f"{covered.end}, so their shapes cannot be compared"
        )
    agreement = _rank_agreement([a for a, _ in paired], [b for _, b in paired])

    if as_json:
        click.echo(
            json.dumps(
                {
                    "points": len(paired),
                    "rank_agreement": (
                        None if math.isnan(agreement) else agreement
                    ),
                    "note": "shapes should agree; values cannot, as the public "
                    "index renormalises per request",
                },
                indent=2,
            )
        )
        return

    click.echo(f"# {term} in {geo}: absolute series vs public 0-100 index")
    click.echo(f"# covering: {covered.start}..{covered.end}")
    click.echo("# values cannot match; the index renormalises per request")
    click.echo(f"# months compared: {len(paired)}")
    if math.isnan(agreement):  # too few overlapping months to compare
        click.echo("# too few overlapping months to compare shape")
    else:
        click.echo(
            f"# rank agreement: {agreement:.2f} (1.0 = identical ordering)"
        )


def _pair_by_month(absolute, indexed) -> list[tuple[float, float]]:
    """Line the two series up on the months they share.

    Bucketed by month rather than matched on exact dates because `graph`
    chooses its own resolution: the same request can come back daily, weekly or
    monthly depending on the span, so its labels need not coincide with the
    absolute series at all.
    """
    monthly: dict[tuple[int, int], list[float]] = {}
    for when, value in indexed:
        monthly.setdefault((when.year, when.month), []).append(value)

    paired = []
    for record in absolute:
        key = (record.date_start.year, record.date_start.month)
        if key in monthly:
            paired.append((record.value, sum(monthly[key]) / len(monthly[key])))

    return paired


def _rank_agreement(left: list[float], right: list[float]) -> float:
    """Fraction of pairs ordered the same way in both series.

    Deliberately a descriptive agreement measure, not a correlation coefficient
    with a p-value: the tool reports shape, the caller runs their own test.
    """
    concordant = discordant = 0

    for i in range(len(left)):
        for j in range(i + 1, len(left)):
            here, there = left[i] - left[j], right[i] - right[j]

            # A pair tied in either series carries no ordering information, so
            # it belongs in neither total. Counting ties as disagreement made
            # two identically flat series report zero agreement -- and flat
            # stretches are exactly what a censored series is full of.
            if here == 0 or there == 0:
                continue

            if here * there > 0:
                concordant += 1
            else:
                discordant += 1

    # Fewer than two ordered pairs cannot agree or disagree about shape;
    # reporting 1.0 would read as perfect agreement on no evidence.
    if not concordant and not discordant:
        return float("nan")

    return concordant / (concordant + discordant)
