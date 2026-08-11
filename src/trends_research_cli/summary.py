"""Descriptive summaries over an exact window.

The line this tool draws: arithmetic over values the caller can also see is in
scope; anything producing a verdict is not. A mean over six visible daily
points is the former. There are no p-values here and there never will be.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Sequence

from trends_research_cli.record import Record

SUMMARIES: dict[str, Callable[[Sequence[float]], float]] = {
    "mean": statistics.fmean,
    "median": statistics.median,
    "sum": sum,
    "max": max,
    "min": min,
}


def summarise(records: list[Record], *, how: str) -> list[Record]:
    """Collapse each series to one value over the dates it actually covers.

    Computed from the daily values already fetched, never by asking the API for
    a coarser interval — it cannot aggregate an arbitrary window, only whole
    calendar periods.

    Each result's span comes from its own records rather than from the request.
    Under ``--by year`` one requested window covers every year at once, so
    stamping that span on each year's mean would claim a coverage no value has
    — and those dates are exactly the provenance a published number is cited
    with.
    """
    reduce = SUMMARIES[how]

    grouped: dict[tuple[str, str], list[Record]] = {}
    for record in records:
        grouped.setdefault((record.term, record.group), []).append(record)

    return [
        Record(
            date_start=min(record.date_start for record in group),
            date_end=max(record.date_end for record in group),
            term=term,
            group=key,
            value=float(reduce([record.value for record in group])),
        )
        for (term, key), group in grouped.items()
    ]
