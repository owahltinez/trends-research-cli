"""The human table and its pivot rule.

Machine formats always emit tidy long format. Only the human table pivots, and
only when exactly one axis varies — otherwise a column would have to mean two
things at once, so it falls back to long format and says so.
"""

from __future__ import annotations

from dataclasses import dataclass

from gtrendscli.record import SCHEMA, By, Record


@dataclass(frozen=True)
class Table:
    """A rendered grid of strings, ready to print."""

    columns: list[str]
    rows: list[list[str]]
    pivoted: bool
    """False when two axes varied and the grid fell back to long format."""


def format_value(value: float) -> str:
    """Format a value for display without ever manufacturing a zero.

    A zero means *no activity* or *too few queries to release*, so rounding a
    small non-zero value down to ``0.0`` would invent that ambiguity where the
    data has none. Machine formats carry full precision regardless.
    """
    if value == 0:
        return "0"

    # Below the one-decimal threshold, switch to significant figures so the
    # value stays visibly distinct from a true zero.
    if abs(value) < 0.1:
        return f"{value:.3g}"

    return f"{value:.1f}"


def _is_numeric(cells: list[str]) -> bool:
    return any(cells) and all(
        cell.replace(".", "").replace("-", "").isdigit()
        for cell in cells
        if cell
    )


def render(table: Table) -> str:
    """Lay the grid out as aligned plain text, numbers to the right."""
    grid = [table.columns, *table.rows]
    widths = [
        max(len(row[i]) for row in grid) for i in range(len(table.columns))
    ]

    numeric = [
        _is_numeric([row[i] for row in table.rows])
        for i in range(len(table.columns))
    ]

    lines = []
    for row in grid:
        cells = [
            cell.rjust(width) if is_number else cell.ljust(width)
            for cell, width, is_number in zip(row, widths, numeric, strict=True)
        ]
        lines.append("  ".join(cells).rstrip())

    return "\n".join(lines)


def _distinct(values: list[str]) -> list[str]:
    """Preserve first-seen order, which is the order the caller asked for."""
    return list(dict.fromkeys(values))


def _row_key(record: Record, by: By) -> str:
    # Overlaid years share a column of calendar days, so the year is dropped
    # from the key and becomes the column instead.
    if by is By.YEAR:
        return record.date_start.strftime("%m-%d")
    return record.date_start.isoformat()


def _long_table(records: list[Record]) -> Table:
    rows = [
        [
            record.date_start.isoformat(),
            record.date_end.isoformat(),
            record.term,
            record.group,
            format_value(record.value),
        ]
        for record in records
    ]
    return Table(columns=list(SCHEMA), rows=rows, pivoted=False)


def _region_table(records: list[Record], terms: list[str]) -> Table:
    """Regions down the page, terms across it.

    A sub-national breakdown covers one period, so putting regions in columns
    would produce a single row hundreds of columns wide. The period is constant
    and stated in the header rather than repeated on every row; machine formats
    still carry it per record.
    """
    values = {(r.group, r.term): r.value for r in records}
    regions = _distinct([r.group for r in records])

    # Highest first, since the question is which places stand out.
    regions.sort(key=lambda code: (-values.get((code, terms[0]), 0.0), code))

    return Table(
        columns=["region", *terms],
        rows=[
            [
                region,
                *(
                    format_value(values[(region, term)])
                    if (region, term) in values
                    else ""
                    for term in terms
                ),
            ]
            for region in regions
        ],
        pivoted=True,
    )


def to_table(records: list[Record], *, by: By) -> Table:
    """Arrange records into a printable grid.

    Columns are the varying axis: the terms when grouping by date, otherwise
    the groups. If both vary there is no honest pivot, so the long format is
    returned with ``pivoted`` false.
    """
    if not records:
        return Table(columns=list(SCHEMA), rows=[], pivoted=False)

    terms = _distinct([record.term for record in records])
    groups = _distinct([record.group for record in records if record.group])

    if by is By.REGION and groups:
        return _region_table(records, terms)

    if groups and len(terms) > 1:
        return _long_table(records)

    columns = groups or terms
    column_of = (lambda r: r.group) if groups else (lambda r: r.term)

    # Daily rows describe a single day, so two identical date columns would be
    # noise; anything coarser must show the period it actually covers.
    spans_periods = any(r.date_start != r.date_end for r in records)
    date_columns = ["date_start", "date_end"] if spans_periods else ["date"]

    cells = {(_row_key(r, by), column_of(r)): r.value for r in records}

    # Overlaid years share a row key but not a period, so no single date_end
    # is true for the row; the per-record values stay in the machine formats.
    ends = (
        {}
        if by is By.YEAR
        else {_row_key(r, by): r.date_end.isoformat() for r in records}
    )
    if by is By.YEAR and spans_periods:
        date_columns = ["date"]
        spans_periods = False

    rows = []
    for key in sorted(dict.fromkeys(_row_key(r, by) for r in records)):
        leading = [key, ends[key]] if spans_periods else [key]
        values = [
            format_value(cells[(key, column)]) if (key, column) in cells else ""
            for column in columns
        ]
        rows.append(leading + values)

    return Table(columns=date_columns + columns, rows=rows, pivoted=True)
