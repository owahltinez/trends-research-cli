"""Splitting long requests under the point ceiling.

Daily data works to roughly 380-430 points per request and the ceiling counts
``terms x points``. Chunks are concatenated with **no bridging factor**: the
values are absolute probabilities, so joining two windows is just appending.
Any rescaling at the seam would be the double-normalisation error this tool
exists to prevent.
"""

from __future__ import annotations

from gtrendscli.dates import DateRange, Period

MAX_POINTS = 380
"""Conservative end of the observed 380-430 ceiling."""


def chunk_periods(
    periods: list[Period], *, terms: int, max_points: int = MAX_POINTS
) -> list[DateRange]:
    """Group whole periods into contiguous ranges each request can return.

    Chunking on periods rather than days means a coarse interval packs far more
    calendar time into one request, which is what the API actually allows.
    """
    if terms < 1:
        raise ValueError("at least one term is required")

    per_chunk = max_points // terms
    if per_chunk < 1:
        raise ValueError(
            f"too many terms for one request: {terms} terms exceeds the "
            f"{max_points}-point ceiling even for a single period"
        )

    # Chunks abut exactly, so concatenating their results neither gaps nor
    # double-counts a period.
    return [
        DateRange(batch[0].start, batch[-1].end)
        for batch in (
            periods[index : index + per_chunk]
            for index in range(0, len(periods), per_chunk)
        )
    ]
