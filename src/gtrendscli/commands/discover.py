"""`gtrends queries` and `gtrends topics`.

Two plain nouns rather than one `related` group, because they return different
things: queries are the raw strings people typed, topics are entities with IDs
that feed straight back into `series`.
"""

from __future__ import annotations

import json

import click

from gtrendscli import helptext
from gtrendscli.api.endpoints import PROPERTIES, Endpoint, build_params
from gtrendscli.api.parse import parse_items
from gtrendscli.commands.filters import resolve_category
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
from gtrendscli.output.result import one_line
from gtrendscli.output.table import Table, render
from gtrendscli.quality import clamp_warnings, freshness_warning
from gtrendscli.session import require_client
from gtrendscli.terms import free_text_warning

MONTH_NOTE = (
    "month granularity is a hard API limit here: this covers whole months, so "
    "it is never evidence about a specific week or day"
)


def _month_span(
    date_from: str, date_to: str | None
) -> tuple[DateRange, list[str]]:
    """Clamp to whole months, reporting what that dropped.

    These endpoints reject anything shorter than a month, and a caller whose
    window was quietly trimmed by seven weeks needs to be told.
    """
    clamped = clamp(
        parse_range(date_from, date_to, today=today_utc()), Interval.MONTH
    )
    span = DateRange(clamped.periods[0].start, clamped.periods[-1].end)
    return span, clamp_warnings(clamped)


def _fetch_items(
    client,
    endpoint: Endpoint,
    term: str,
    geo: str,
    span: DateRange,
    category: int | None = None,
    trends_property: str | None = None,
):
    body = client.fetch(
        endpoint,
        build_params(
            endpoint,
            terms=[term],
            geo=geo,
            span=span,
            category=category,
            trends_property=trends_property,
        ),
    )
    return parse_items(body)


def _render(
    rows: list[dict],
    header: list[str],
    warnings: list[str],
    notes: list[str] | None = None,
) -> None:
    for line in header:
        click.echo(f"# {one_line(line)}")
    for warning in warnings:
        click.echo(f"# warning: {one_line(warning)}")
    for note in notes or []:
        click.echo(f"# note: {one_line(note)}")

    columns = ["title", "value"] + (
        ["mid"] if any("mid" in r for r in rows) else []
    )
    click.echo(
        render(
            Table(
                columns=[*columns, "breakout"],
                rows=[
                    [
                        *(str(row.get(name, "")) for name in columns),
                        "yes" if row.get("breakout") else "",
                    ]
                    for row in rows
                ],
                pivoted=True,
            )
        )
    )


def _build(kind: str, top: Endpoint, rising_endpoint: Endpoint, doc: str):
    """Build a `queries` or `topics` command; they differ only in endpoint."""

    @click.command(
        name=kind,
        help=doc,
        epilog=f"""Examples:

\b
  gtrends {kind} /m/0cycc --geo US --from 2025-07
  gtrends {kind} /m/0cycc --geo US --from 2026-07 --rising --top 10
  gtrends {kind} /m/0cycc --geo US --from 2026-07 --vs 2025-07

Month-granular: a range containing no whole month is rejected (exit 1).""",
    )
    @click.argument("term")
    @click.option("--geo", required=True, help=helptext.GEO)
    @click.option(
        "--from",
        "date_from",
        required=True,
        help=helptext.DATE_FROM + " " + helptext.MONTH_ONLY,
    )
    @click.option("--to", "date_to", help=helptext.DATE_TO)
    @click.option("--rising", is_flag=True, help="Rising rather than top.")
    @click.option("--category", help=helptext.CATEGORY)
    @click.option(
        "--category-id", type=click.IntRange(min=0), help=helptext.CATEGORY_ID
    )
    @click.option(
        "--property",
        "trends_property",
        type=click.Choice(sorted(PROPERTIES)),
        help=helptext.PROPERTY,
    )
    @click.option(
        "--vs",
        "versus",
        help="Also fetch another period and print it alongside, e.g. 2025-07.",
    )
    @click.option(
        "--top",
        "limit",
        type=click.IntRange(min=1),
        help="Keep only the first N rows.",
    )
    @click.option("--json", "as_json", is_flag=True, help=helptext.JSON)
    @click.option(
        "--plain",
        "as_plain",
        is_flag=True,
        help="Bare values per line: MIDs for topics, strings for queries.",
    )
    @click.pass_obj
    def command(
        obj,
        term,
        geo,
        date_from,
        date_to,
        rising,
        category,
        category_id,
        trends_property,
        versus,
        limit,
        as_json,
        as_plain,
    ):
        client = require_client(obj)

        # Silently picking one would hand a pipeline a format it did not ask
        # for; `series` refuses the same combination.
        if as_json and as_plain:
            raise click.UsageError(
                "choose one output format, got --json --plain"
            )

        # `--plain` is bare values with no room for a second series, so it
        # would spend the extra request and discard the answer.
        if as_plain and versus:
            raise click.UsageError(
                "--plain cannot show a --vs comparison; use --json"
            )

        endpoint = rising_endpoint if rising else top
        warnings = [w for w in [free_text_warning([term])] if w]

        chosen, category_label, notes = resolve_category(category, category_id)

        try:
            span, dropped = _month_span(date_from, date_to)
            warnings += [
                f"requested window {span.start}..{span.end}: {warning}"
                if versus
                else warning
                for warning in dropped
            ]
            rows = _fetch_items(
                client, endpoint, term, geo, span, chosen, trends_property
            )

            comparison = None
            other = span
            if versus:
                other, other_dropped = _month_span(versus, None)
                # Say which window each caveat belongs to. Unlabelled, a
                # provisional-data warning for the comparison reads as one
                # about the primary window, which may be years older.
                warnings += [
                    f"comparison window {other.start}..{other.end}: {warning}"
                    for warning in other_dropped
                ]
                comparison = _fetch_items(
                    client, endpoint, term, geo, other, chosen, trends_property
                )
                if fresh := freshness_warning(other.end, today=today_utc()):
                    warnings.append(f"comparison window: {fresh}")
        except (DateFormatError, ClampError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc
        except Exception as exc:
            raise guard_api(exc) from exc

        if fresh := freshness_warning(span.end, today=today_utc()):
            warnings.append(fresh)

        if not rows:
            warnings.append(
                "the API returned no items for this term, geo and period"
            )

        if limit:
            rows = rows[:limit]
            # `is not None`, not truthiness: an empty comparison is a result,
            # and turning it into "no comparison" hides that the other period
            # returned nothing.
            if comparison is not None:
                comparison = comparison[:limit]

        if as_plain:
            # Topics compose into `series`, so their MIDs are the useful value.
            key = "mid" if any("mid" in row for row in rows) else "title"
            click.echo("\n".join(str(row.get(key, "")) for row in rows))
            return

        if as_json:
            click.echo(
                json.dumps(
                    {
                        "meta": {
                            "term": term,
                            "geo": geo,
                            "endpoint": endpoint.value,
                            "date_start": span.start.isoformat(),
                            "date_end": span.end.isoformat(),
                            "granularity": "month",
                            "category": category_label,
                            "property": trends_property or "web",
                            "comparison_start": (
                                other.start.isoformat() if versus else None
                            ),
                            "comparison_end": (
                                other.end.isoformat() if versus else None
                            ),
                        },
                        "warnings": warnings,
                        "notes": [*notes, MONTH_NOTE],
                        "items": rows,
                        "comparison": comparison,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return

        _render(
            rows,
            [
                f"term: {term}  geo: {geo}  endpoint: {endpoint.value}",
                f"covering: {span.start}..{span.end}",
            ],
            warnings,
            [*notes, MONTH_NOTE],
        )

        if comparison is not None:
            click.echo()
            click.echo(
                f"# comparison period: {other.start}..{other.end}"
                f" (from --vs {versus})"
            )
            _render(comparison, [], [])

    return command


queries = _build(
    "queries",
    Endpoint.TOP_QUERIES,
    Endpoint.RISING_QUERIES,
    "What strings people typed alongside this term.",
)

topics = _build(
    "topics",
    Endpoint.TOP_TOPICS,
    Endpoint.RISING_TOPICS,
    "What entities co-occur with this term. Output feeds into `series`.",
)
