"""Turning API responses into records.

Two undocumented details are handled here. `timelinesForHealth` labels points
with ``Jul 01 2025`` at day and week resolution but ``Jul 2025`` at month, and
in every case labels a period by its first day only — the coverage each value
describes is never stated and must be reconstructed.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from trends_research_cli.dates import DateRange, Interval, period_end
from trends_research_cli.record import Record

# Coarser resolutions drop parts of the label: month loses the day,
# year loses both.
_LABEL_FORMATS = {
    Interval.DAY: "%b %d %Y",
    Interval.WEEK: "%b %d %Y",
    Interval.MONTH: "%b %Y",
    Interval.YEAR: "%Y",
}


def _parse_label(text: str, interval: Interval) -> date:
    """Read a point's date label, refusing to guess at an unknown shape."""
    try:
        return datetime.strptime(text, _LABEL_FORMATS[interval]).date()
    except ValueError as exc:
        raise ValueError(
            f"unrecognised date label {text!r} in a {interval.value} response; "
            f"expected the format {_LABEL_FORMATS[interval]!r}"
        ) from exc


def parse_timelines(
    body: dict[str, Any], *, interval: Interval, group: str = ""
) -> list[Record]:
    """Flatten a `timelinesForHealth` response into records.

    A malformed label raises rather than being skipped: dropping a point would
    quietly understate coverage, which is the failure this tool exists to stop.
    """
    records = []

    for line in body.get("lines", []):
        term = line.get("term", "")

        for point in line.get("points", []):
            start = _parse_label(point["date"], interval)
            records.append(
                Record(
                    date_start=start,
                    date_end=period_end(start, interval),
                    term=term,
                    group=group,
                    value=float(point["value"]),
                )
            )

    return records


def parse_index_points(body: dict[str, Any]) -> list[tuple[date, float]]:
    """Parse `graph` points into bare (date, value) pairs.

    `graph` is the odd one out twice over: it labels points with ISO dates
    rather than the timelines format, and it picks its own resolution from the
    span with no parameter to control it -- a six-month request comes back
    daily. No period is inferred here, because the response does not say what
    each point covers and guessing would misstate coverage.
    """
    points = []

    for line in body.get("lines", []):
        for point in line.get("points", []):
            label = point["date"]
            try:
                when = datetime.strptime(label, "%Y-%m-%d").date()
            except ValueError as exc:
                raise ValueError(
                    f"unrecognised date label {label!r} in a graph response; "
                    f"expected ISO YYYY-MM-DD"
                ) from exc
            points.append((when, float(point["value"])))

    return points


def parse_regions(
    body: dict[str, Any], *, term: str, span: DateRange
) -> list[Record]:
    """Flatten a `regions` response into records.

    The endpoint returns one value per sub-region for the whole window rather
    than a series, so every record carries the full requested span as its
    period — that is genuinely the coverage of each number.
    """
    return [
        Record(
            date_start=span.start,
            date_end=span.end,
            term=term,
            group=region["regionCode"],
            value=float(region["value"]),
        )
        for region in body.get("regions", [])
    ]


def parse_items(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a `*Queries` / `*Topics` response into title/value/mid rows.

    Topics carry a `mid` and queries do not, so the key is preserved only when
    present rather than filled with a placeholder that could be mistaken for an
    entity ID.
    """
    rows = []

    for item in body.get("item", []):
        row = {"title": item.get("title", ""), "value": item.get("value")}
        if "mid" in item:
            row["mid"] = item["mid"]
        row["breakout"] = bool(item.get("isBreakout", False))
        rows.append(row)

    return rows
