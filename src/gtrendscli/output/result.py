"""What every command produces, and how it is emitted.

Machine formats are always tidy long format and never pivot; the human table
pivots only when exactly one axis varies. Warnings travel with the data in
every format, so an agent detects a bleeding window or a censored series from
the output rather than from prose.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gtrendscli.output.table import render, to_table
from gtrendscli.record import SCHEMA, By, Record

METRIC = "P(term | date AND geo) x 10,000,000"

ATTRIBUTION = "Data source: Google Trends (https://www.google.com/trends)"
"""Reusing Trends data requires crediting Google, so every artefact carries
the citation rather than leaving a journalist to remember it."""


def one_line(value: object) -> str:
    """Flatten a value that is about to become a `#` comment line.

    A newline in a geo or a term would otherwise close the comment and forge a
    data row: a reader that strips `#` lines takes whatever follows as real.
    Control characters are escaped rather than dropped, so nothing is silently
    lost and the oddity stays visible.
    """
    text = str(value)
    return "".join(
        rf"\x{ord(char):02x}" if ord(char) < 32 else char for char in text
    )


@dataclass
class Result:
    """Records plus everything needed to interpret them."""

    records: list[Record]
    meta: dict[str, Any]
    by: By = By.DATE

    warnings: list[str] = field(default_factory=list)
    """Data-quality problems with *this* answer. `--strict` counts these."""

    notes: list[str] = field(default_factory=list)
    """Caveats that hold whatever the data says -- a hard API limit, a naming
    scheme. Always shown, never counted by `--strict`, which would otherwise
    fail on flawless data and become useless."""

    def as_dicts(self) -> list[dict[str, Any]]:
        """Tidy long format, with values at full precision."""
        return [
            {
                "date_start": record.date_start.isoformat(),
                "date_end": record.date_end.isoformat(),
                "term": record.term,
                "group": record.group,
                "value": record.value,
            }
            for record in self.records
        ]


def stamp(**fields: Any) -> dict[str, Any]:
    """Build the metadata block every artefact carries."""
    return {
        "unit": METRIC,
        "source": ATTRIBUTION,
        "retrieved_at": datetime.now(UTC).isoformat(),
        **fields,
    }


def to_json(result: Result) -> str:
    """Tidy long format with metadata and warnings alongside."""
    return json.dumps(
        {
            "meta": result.meta,
            "warnings": result.warnings,
            "notes": result.notes,
            "records": result.as_dicts(),
        },
        indent=2,
        ensure_ascii=False,
    )


def to_csv(result: Result) -> str:
    """Tidy long format, with the metadata as leading comment lines.

    Comment lines keep the unit attached to the numbers; every reader that
    matters skips them, and a reader who sees a bare column of values cannot
    check them against the API.
    """
    buffer = io.StringIO()
    for key, value in result.meta.items():
        buffer.write(f"# {key}: {one_line(value)}\n")
    for warning in result.warnings:
        buffer.write(f"# warning: {one_line(warning)}\n")
    for note in result.notes:
        buffer.write(f"# note: {one_line(note)}\n")

    writer = csv.DictWriter(buffer, fieldnames=SCHEMA)
    writer.writeheader()
    writer.writerows(result.as_dicts())

    return buffer.getvalue()


def to_plain(result: Result) -> str:
    """Bare values, one per line, so commands compose in a shell."""
    return "\n".join(str(record.value) for record in result.records)


def to_text(result: Result) -> str:
    """The human table, headed by its metadata and warnings."""
    lines = [
        f"# {key}: {one_line(value)}" for key, value in result.meta.items()
    ]
    lines += [f"# warning: {one_line(warning)}" for warning in result.warnings]
    lines += [f"# note: {one_line(note)}" for note in result.notes]

    table = to_table(result.records, by=result.by)
    if not table.pivoted and result.records:
        lines.append(
            "# note: two axes vary, so this is long format rather than a grid"
        )

    lines.append(render(table))
    return "\n".join(lines)


def write_parquet(result: Result, path: Path) -> None:
    """Write tidy long format, with the metadata in the file's own schema."""
    # Imported here, not at module level: parquet is an optional extra, and a
    # top-level import would make it a hard dependency of every command.
    try:
        import pyarrow  # noqa: PLC0415
        import pyarrow.parquet  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "parquet output needs the optional extra: uv sync --extra parquet"
        ) from exc

    rows = result.as_dicts()

    # Warnings ride along in the file's own metadata. A reader that sees only
    # values has no way to learn the window was clamped or the series mostly
    # suppressed, which is exactly what it would need to know.
    metadata = {key: str(value) for key, value in result.meta.items()}
    metadata["warnings"] = json.dumps(result.warnings, ensure_ascii=False)
    metadata["notes"] = json.dumps(result.notes, ensure_ascii=False)

    table = pyarrow.table(
        {name: [row[name] for row in rows] for name in SCHEMA},
        metadata=metadata,
    )
    pyarrow.parquet.write_table(table, path)
