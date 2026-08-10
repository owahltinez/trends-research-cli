"""Orchestrating requests into records.

Chunked windows are concatenated by appending and nothing else. The values are
absolute probabilities, so a bridging factor at the seam would be the
double-normalisation error this tool exists to prevent.
"""

from __future__ import annotations

from gtrendscli.api.client import Client
from gtrendscli.api.endpoints import Endpoint, build_params
from gtrendscli.api.parse import parse_regions, parse_timelines
from gtrendscli.chunking import chunk_periods
from gtrendscli.dates import DateRange, Interval, Period
from gtrendscli.record import Record


def fetch_timelines(
    client: Client,
    *,
    terms: list[str],
    geo: str,
    periods: list[Period],
    interval: Interval,
    group: str = "",
) -> list[Record]:
    """Fetch a series, splitting past the point ceiling and concatenating."""
    records: list[Record] = []

    for chunk in chunk_periods(periods, terms=len(terms)):
        body = client.fetch(
            Endpoint.TIMELINES,
            build_params(
                Endpoint.TIMELINES,
                terms=terms,
                geo=geo,
                span=chunk,
                interval=interval,
            ),
        )
        records.extend(parse_timelines(body, interval=interval, group=group))

    return records


def fetch_regions(
    client: Client, *, terms: list[str], geo: str, span: DateRange
) -> list[Record]:
    """Fetch one value per sub-region, per term.

    The endpoint takes a single term, so several terms mean several calls. It
    honours full dates, so no clamping is needed at any range length.
    """
    records: list[Record] = []

    for term in terms:
        body = client.fetch(
            Endpoint.REGIONS,
            build_params(Endpoint.REGIONS, terms=[term], geo=geo, span=span),
        )
        records.extend(parse_regions(body, term=term, span=span))

    return records
