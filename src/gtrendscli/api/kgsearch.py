"""Knowledge Graph entity lookup.

Runs on the same API key as Trends but needs the Knowledge Graph Search API
enabled separately on the project, which `gtrends doctor` checks.

Two undocumented details, both verified live: `@id` comes back prefixed
(``kg:/m/087t7g``) but the ``ids`` parameter rejects that prefix with a 400 and
wants the bare MID; and plenty of MIDs that Trends serves data for are absent
from this index entirely, which is why it is never the only source consulted.
"""

from __future__ import annotations

from dataclasses import dataclass

from gtrendscli.api.client import Client

SEARCH_URL = "https://kgsearch.googleapis.com/v1/entities:search"

KG_PREFIX = "kg:"


@dataclass(frozen=True)
class Candidate:
    """One possible entity for a name."""

    mid: str
    name: str
    description: str
    source: str
    score: float = 0.0


def _as_candidate(element: dict, source: str) -> Candidate | None:
    result = element.get("result", {})
    identifier = result.get("@id", "")

    # Strip the prefix so the MID matches what Trends and `--terms` use.
    mid = identifier.removeprefix(KG_PREFIX)
    if not mid.startswith(("/m/", "/g/")):
        return None

    return Candidate(
        mid=mid,
        name=result.get("name", ""),
        description=result.get("description", ""),
        source=source,
        score=float(element.get("resultScore", 0.0)),
    )


def search(client: Client, query: str, *, limit: int = 10) -> list[Candidate]:
    """Find entities matching a name."""
    body = client.fetch_url(
        SEARCH_URL,
        [("query", query), ("limit", str(limit))],
        label="kgsearch",
    )
    found = (
        _as_candidate(element, "kgsearch")
        for element in body.get("itemListElement", [])
    )
    return [candidate for candidate in found if candidate]


def lookup(client: Client, mid: str) -> Candidate | None:
    """Return the entity's current name, or None if this index lacks it.

    Absence is not evidence the ID is wrong: MIDs that Trends serves data for
    are routinely missing here.
    """
    body = client.fetch_url(SEARCH_URL, [("ids", mid)], label="kgsearch")
    for element in body.get("itemListElement", []):
        if candidate := _as_candidate(element, "kgsearch"):
            return candidate

    return None
