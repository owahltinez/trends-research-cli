"""`gtrends series` — the numbers."""

from __future__ import annotations

import click

from gtrendscli import helptext
from gtrendscli.api.client import Client
from gtrendscli.api.endpoints import Endpoint
from gtrendscli.dates import (
    ClampError,
    DateFormatError,
    DateRange,
    Interval,
    Period,
    clamp,
    parse_calendar_window,
    parse_range,
    parse_years,
    today_utc,
)
from gtrendscli.exits import StrictFailure, guard_api
from gtrendscli.fetching import fetch_regions, fetch_timelines
from gtrendscli.output import options
from gtrendscli.output.result import Result, stamp
from gtrendscli.quality import (
    censoring_warnings,
    clamp_warnings,
    coverage,
    freshness_warning,
)
from gtrendscli.record import By, Record
from gtrendscli.session import require_client
from gtrendscli.summary import SUMMARIES, summarise
from gtrendscli.terms import free_text_warning


def _clamped(span: DateRange, interval: Interval) -> tuple[list, list[str]]:
    """Reduce a range to whole periods, reporting what fell off each end."""
    result = clamp(span, interval)
    return result.periods, clamp_warnings(result)


def _by_date(
    client: Client,
    terms: list[str],
    geo: str,
    span: DateRange,
    interval: Interval,
) -> tuple[list[Record], DateRange, list[str]]:
    periods, warnings = _clamped(span, interval)
    covered = DateRange(periods[0].start, periods[-1].end)
    records = fetch_timelines(
        client, terms=terms, geo=geo, periods=periods, interval=interval
    )
    return records, covered, warnings


REGION_NOTES = [
    "region codes are Google's own scheme. They often match ISO-3166-2 but "
    "not always, and for some countries reflect superseded administrative "
    "divisions",
    "splitting sub-nationally pushes low-volume terms below the release "
    "threshold: a term visible nationally can be zero in every region",
]


def _by_region(
    client: Client, terms: list[str], geo: str, span: DateRange
) -> tuple[list[Record], DateRange, list[str]]:
    # No clamping: `regions` honours full dates at any range length.
    records = fetch_regions(client, terms=terms, geo=geo, span=span)

    # These hold whatever the data says, so they are notes rather than
    # warnings; as warnings they made `--strict` fail on flawless data.
    return records, span, []


def _region_zero_warning(records: list[Record]) -> list[str]:
    """One warning about how many regions are zero, not one warning each.

    Each region is a single value, and the censoring threshold means nothing
    applied to a population of one -- it would fire for every zero region and
    bury everything else.
    """
    if not records:
        return []

    zeros = [record.group for record in records if record.value == 0]
    if not zeros:
        return []

    listed = ", ".join(sorted(zeros)[:8])
    more = "" if len(zeros) <= 8 else f" and {len(zeros) - 8} more"
    return [
        f"{len(zeros)} of {len(records)} regions are zero ({listed}{more}). "
        f"A zero means no activity OR too few queries to release, so this is "
        f"the release threshold as much as it is geography."
    ]


def _by_year(
    client: Client,
    terms: list[str],
    geo: str,
    date_from: str,
    date_to: str | None,
    years: list[int],
    interval: Interval,
) -> tuple[list[Record], DateRange, list[str]]:
    records: list[Record] = []
    warnings: list[str] = []
    fetched: list[Period] = []

    for year in years:
        window = parse_calendar_window(date_from, date_to, year=year)
        periods, dropped = _clamped(window, interval)
        warnings.extend(dropped)
        fetched.extend(periods)
        records.extend(
            fetch_timelines(
                client,
                terms=terms,
                geo=geo,
                periods=periods,
                interval=interval,
                group=str(year),
            )
        )

    # The covered span describes what was actually fetched, so it comes from
    # the clamped periods, not the requested windows -- otherwise a clamp is
    # reported honestly on `--by date` and misreported here. Extremes rather
    # than first and last, because `--years 2026,2020` is legitimate.
    covered = DateRange(
        min(period.start for period in fetched),
        max(period.end for period in fetched),
    )
    return records, covered, warnings


MAX_YEARS = 30
"""Each year costs its own request, and Trends data starts in 2004."""


def _bounded_years(text: str) -> list[int]:
    """Parse `--years`, refusing a range that would spend absurd quota."""
    years = parse_years(text)

    if len(years) > MAX_YEARS:
        raise click.UsageError(
            f"--years covers {len(years)} years, and each one is a separate "
            f"request; {MAX_YEARS} is the most this will spend at once"
        )

    return years


def _validate(
    by: By, interval: Interval, how: str | None, years: str | None
) -> None:
    """Refuse combinations that cannot be answered honestly."""
    if by is By.YEAR and not years:
        raise click.UsageError(
            "--by year needs --years, e.g. --years 2021-2026"
        )

    if by is not By.YEAR and years:
        raise click.UsageError("--years only applies with --by year")

    # `--summary` over one value per region is arithmetic on a single number.
    if by is By.REGION and how:
        raise click.UsageError(
            "--by region already returns one value per region, so --summary "
            "has nothing to collapse"
        )

    if by is By.REGION and interval is not Interval.DAY:
        raise click.UsageError(
            "--by region returns one value per region for the whole range, so "
            "--interval does not apply"
        )

    # The API cannot aggregate an arbitrary window, only whole calendar
    # periods, so a summary must be computed from daily values here.
    if how and interval is not Interval.DAY:
        raise click.UsageError(
            f"--summary is computed from daily values over the exact dates "
            f"given; --interval {interval.value} would answer a different "
            f"question. Drop --interval or drop --summary"
        )


@click.command(
    epilog="""Examples:

\b
  gtrends series /m/0cycc --geo US --from 2025-07-01 --to 2025-07-07
  gtrends series /m/0cycc /m/07__7 --geo US --from 2025-07
  gtrends series /m/0cycc --geo US --from 2025-07 --by region
  gtrends series /m/0cycc --geo US --from 07-21 --to 07-23 \\
      --by year --years 2023-2025
  gtrends series /m/0cycc --geo US --from 2025-07-21 --to 2025-07-26 \\
      --summary mean --json

Run `gtrends guide` for the full manual, including the clamp rule and
exit codes.""",
)
@click.argument("terms", nargs=-1, required=True)
@click.option("--geo", required=True, help=helptext.GEO)
@click.option(
    "--from",
    "date_from",
    required=True,
    help=helptext.DATE_FROM + " With --by year, give MM-DD instead.",
)
@click.option("--to", "date_to", help=helptext.DATE_TO)
@click.option(
    "--interval",
    type=click.Choice([choice.value for choice in Interval]),
    default=Interval.DAY.value,
    show_default=True,
    help=(
        "Calendar period size. A range containing no whole period is an "
        "error; a wider one is clamped to whole periods and the dropped "
        "partials are reported."
    ),
)
@click.option(
    "--by",
    "by_axis",
    type=click.Choice([choice.value for choice in By]),
    default=By.DATE.value,
    show_default=True,
    help="Grouping besides time.",
)
@click.option("--years", help="With --by year: 2021-2026 or 2021,2023,2026.")
@click.option(
    "--summary",
    "how",
    type=click.Choice(sorted(SUMMARIES)),
    help="Collapse each series to one value over the exact dates given.",
)
@options.output_options
@click.pass_obj
def series(
    obj: object,
    terms: tuple[str, ...],
    geo: str,
    date_from: str,
    date_to: str | None,
    interval: str,
    by_axis: str,
    years: str | None,
    how: str | None,
    **output: object,
) -> None:
    """Fetch absolute probability series for one or more terms.

    Values are exactly what the API returns and are never rescaled:

        value = P(term | date AND geography) x 10,000,000

    Prefer entity IDs (/m/... or /g/...) to free text; a bare string matches
    spellings and warns. Zeros mean "no activity OR too few queries to
    release" and are reported as pct_zero. Days are binned in UTC and the last
    two days are provisional.
    """
    client = require_client(obj)
    resolution, by = Interval(interval), By(by_axis)
    _validate(by, resolution, how, years)

    warnings = [
        warning for warning in [free_text_warning(list(terms))] if warning
    ]

    try:
        if by is By.YEAR:
            records, covered, dropped = _by_year(
                client,
                list(terms),
                geo,
                date_from,
                date_to,
                _bounded_years(years or ""),
                resolution,
            )
        else:
            span = parse_range(date_from, date_to, today=today_utc())
            if by is By.REGION:
                records, covered, dropped = _by_region(
                    client, list(terms), geo, span
                )
            else:
                records, covered, dropped = _by_date(
                    client, list(terms), geo, span, resolution
                )
    except (DateFormatError, ClampError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:
        raise guard_api(exc) from exc

    warnings += dropped

    # "The API returned nothing" and "I asked for nothing" must not look alike.
    if not records:
        warnings.append(
            "the API returned no data points for this request; the term, geo "
            "or date range may have no releasable data"
        )
    # Per-region values are single points, so a percentage-zero threshold
    # cannot say anything about them; they get one aggregate warning instead
    # of one apiece, which would bury everything else.
    if by is By.REGION:
        warnings += _region_zero_warning(records)
    else:
        warnings += censoring_warnings(coverage(records))

    if fresh := freshness_warning(covered.end, today=today_utc()):
        warnings.append(fresh)

    if how:
        records = summarise(records, how=how)

    result = Result(
        records=records,
        by=by,
        warnings=warnings,
        notes=REGION_NOTES if by is By.REGION else [],
        meta=stamp(
            geo=geo,
            interval=resolution.value,
            by=by.value,
            endpoint=(
                Endpoint.REGIONS.value
                if by is By.REGION
                else Endpoint.TIMELINES.value
            ),
            date_start=covered.start.isoformat(),
            date_end=covered.end.isoformat(),
            summary=how or "none",
        ),
    )

    options.emit(result, client=client, **output)

    # The receipt is written last so a filesystem problem cannot cost the data
    # whose quota was already spent, but losing it is a warning like any other
    # and `--strict` must see it.
    lost = options.write_receipt_or_warn(
        result,
        client,
        output.get("receipt"),  # type: ignore[arg-type]
    )
    if lost:
        warnings.append(lost)

    if output.get("strict") and warnings:
        raise StrictFailure(f"{len(warnings)} warning(s) under --strict")
