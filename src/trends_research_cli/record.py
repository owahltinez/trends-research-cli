"""The canonical record every command produces.

One row per ``date_start x term x group``. Machine formats emit exactly this and
never pivot, so a pipeline sees a stable schema whatever the command did.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

SCHEMA = ["date_start", "date_end", "term", "group", "value"]


class By(StrEnum):
    """The grouping axis besides time."""

    DATE = "date"
    REGION = "region"
    YEAR = "year"


@dataclass(frozen=True)
class Record:
    """One value, with the coverage it actually describes.

    ``date_start`` and ``date_end`` are always both present, and are equal for
    daily data. Carrying the true period on every row means coverage is visible
    in the data rather than inferred from the request.
    """

    date_start: date
    date_end: date
    term: str
    group: str
    """Region code or year; empty when grouping by date alone."""

    value: float
