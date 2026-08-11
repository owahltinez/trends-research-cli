"""Coverage reporting.

A zero from this API means *no activity* **or** *too few distinct queries to
release*, and the two are indistinguishable. Every series therefore reports how
much of it is zero, so a caller cannot run a test on data that cannot support
one.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta

from trends_research_cli.dates import ClampResult, DateRange
from trends_research_cli.record import Record

CENSORING_THRESHOLD = 50.0
"""Percent zero above which a series is flagged. Mixing resolutions on a series
this sparse produced ratios scattering from 0.14 to 5.02."""


@dataclass(frozen=True)
class Coverage:
    """How much of one series is actually measurable."""

    term: str
    group: str
    count: int
    zero_count: int
    pct_zero: float
    median: float
    maximum: float
    longest_zero_run: int


def _longest_zero_run(values: list[float]) -> int:
    longest = running = 0

    for value in values:
        running = running + 1 if value == 0 else 0
        longest = max(longest, running)

    return longest


def coverage(records: list[Record]) -> list[Coverage]:
    """Summarise each ``(term, group)`` series in the records."""
    grouped: dict[tuple[str, str], list[float]] = {}
    for record in records:
        grouped.setdefault((record.term, record.group), []).append(record.value)

    summaries = []
    for (term, group), values in grouped.items():
        zeros = sum(1 for value in values if value == 0)
        summaries.append(
            Coverage(
                term=term,
                group=group,
                count=len(values),
                zero_count=zeros,
                pct_zero=100.0 * zeros / len(values),
                median=statistics.median(values),
                maximum=max(values),
                longest_zero_run=_longest_zero_run(values),
            )
        )

    return summaries


def censoring_warnings(
    summaries: list[Coverage], *, threshold: float = CENSORING_THRESHOLD
) -> list[str]:
    """Warn for each series too sparse to interpret at face value."""
    warnings = []

    for stats in summaries:
        if stats.pct_zero <= threshold:
            continue

        label = f"{stats.term}" + (f" in {stats.group}" if stats.group else "")
        warnings.append(
            f"{label} is {stats.pct_zero:.1f}% zero "
            f"({stats.zero_count}/{stats.count} points, longest run "
            f"{stats.longest_zero_run}). A zero means no activity OR too few "
            f"queries to release; these are indistinguishable, so treat "
            f"absence here as unmeasured rather than suppressed demand."
        )

    return warnings


SETTLING_DAYS = 2
"""How far behind the current UTC date the API's data horizon sits.

Established by probing: a four-day request ending on or before that horizon
succeeds, while the same request ending a day later returns 400."""


def freshness_warning(end: date, *, today: date) -> str | None:
    """Warn when a range runs up to the present.

    Days are binned in UTC and the current one is only partly elapsed. Because
    the metric is a *share* rather than a count, a partial day comes back
    looking like a perfectly ordinary value -- there is nothing in the number
    itself to reveal that it covers three hours rather than twenty-four.
    """
    if end < today - timedelta(days=SETTLING_DAYS):
        return None

    horizon = today - timedelta(days=SETTLING_DAYS)
    return (
        f"data past {horizon} is provisional. Days are binned in UTC and the "
        f"API's horizon sits about {SETTLING_DAYS} days back: it rejects a "
        f"short request ending here outright, yet a long one spanning it "
        f"returns the trailing days anyway. Because the value is a share and "
        f"not a count, those days look like ordinary numbers rather than "
        f"partial ones, so a late spike is not evidence until it settles."
    )


def _dropped_warning(dropped: DateRange | None, edge: str) -> str | None:
    if dropped is None:
        return None
    return (
        f"dropped partial {edge} period {dropped.start}..{dropped.end}: it "
        f"falls outside the whole calendar periods the API returns"
    )


def clamp_warnings(clamped: ClampResult) -> list[str]:
    """Report the partial periods a clamp trimmed off each end.

    Every command that clamps must say what it dropped, so this lives in one
    place: a second implementation elsewhere once silently lost the reporting.
    """
    return [
        warning
        for warning in (
            _dropped_warning(clamped.dropped_start, "leading"),
            _dropped_warning(clamped.dropped_end, "trailing"),
        )
        if warning
    ]
