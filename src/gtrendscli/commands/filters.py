"""Turning `--category` / `--category-id` into a value and a note.

Shared so the resolution, the mutual exclusion and the containment note read
identically everywhere: a second implementation of an already-correct helper is
how this project has lost a safety property before.
"""

from __future__ import annotations

import click

from gtrendscli import categories as taxonomy
from gtrendscli.categories import CategoryError


def resolve_category(
    category: str | None, category_id: int | None
) -> tuple[int | None, str, list[str]]:
    """Return the id to send, a label for the metadata, and notes.

    The label goes in the header, so the notes describe only what the label
    cannot: what the choice contains, and what contains it.
    """
    if category is not None and category_id is not None:
        raise click.UsageError(
            "choose one of --category or --category-id, not both"
        )

    if category is None and category_id is None:
        return None, "all", []

    # Both forms are checked. The valid ids are a known, finite set, and the
    # API answers an unknown one with a 500 that explains nothing -- so there
    # is no reason to spend a request discovering what we already know.
    try:
        identifier = (
            category_id
            if category_id is not None
            else taxonomy.resolve(category or "")
        )
        described = taxonomy.describe(identifier)
    except CategoryError as exc:
        raise click.ClickException(str(exc)) from None

    notes: list[str] = []

    # Choosing a parent sweeps in its descendants, which is easy to miss and
    # changes what the number means.
    if described.descendants:
        notes.append(
            f"this includes {described.descendants} sub-categories beneath it, "
            f"starting with {', '.join(described.child_names[:5])}"
        )

    # The other direction matters just as much. A run filtered to this
    # category and one filtered to something containing it measure overlapping
    # populations, so putting the two side by side is the same error as
    # dividing a series by a "control" that contains it.
    if described.ancestor_paths:
        notes.append(
            f"it sits inside {', '.join(described.ancestor_paths)}, so results "
            f"filtered to those are not independent of this one and must not "
            f"be compared as if they were"
        )

    for extra in described.all_paths[1:]:
        notes.append(f"the same category is also reachable as {extra}")

    return identifier, f"{described.id} {described.path}", notes
