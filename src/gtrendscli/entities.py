"""Finding entity IDs from two sources.

Getting entity IDs right matters more than any analysis decision, and one
lookup is not enough. Verified live: `/m/0cycc` is what Trends' own topic index
returns for influenza and `timelinesForHealth` serves data for it, yet
`kgsearch` has no record of it at all. Relying on `kgsearch` alone would
discard a working entity as nonexistent.
"""

from __future__ import annotations

from gtrendscli.api.client import Client
from gtrendscli.api.endpoints import Endpoint, build_params
from gtrendscli.api.kgsearch import Candidate, search
from gtrendscli.api.parse import parse_items
from gtrendscli.dates import DateRange


def _from_topics(
    client: Client, query: str, geo: str, span: DateRange
) -> list[Candidate]:
    """Ask the Trends topic index, which knows entities `kgsearch` does not."""
    candidates = []

    for endpoint in (Endpoint.TOP_TOPICS, Endpoint.RISING_TOPICS):
        body = client.fetch(
            endpoint,
            build_params(endpoint, terms=[query], geo=geo, span=span),
        )
        for item in parse_items(body):
            if mid := item.get("mid"):
                candidates.append(
                    Candidate(
                        mid=mid,
                        name=item["title"],
                        description="",
                        source="trends-topics",
                        score=float(item.get("value") or 0),
                    )
                )

    return candidates


def find(
    client: Client, query: str, *, geo: str, span: DateRange, limit: int = 10
) -> list[Candidate]:
    """Merge both indexes, keeping every source that named a given MID.

    A candidate found by both is more trustworthy than one found by either, so
    the sources are recorded rather than collapsed.
    """
    merged: dict[str, Candidate] = {}
    rank: dict[str, tuple[int, int]] = {}

    # The two indexes score on incomparable scales -- `kgsearch` reports
    # relevance to the query, the topic index reports search volume or percent
    # rise. Sorting on the raw numbers puts whatever is merely popular above
    # what was actually asked for, so each source keeps its own ordering and
    # they are interleaved by source instead.
    for priority, group in enumerate(
        (
            search(client, query, limit=limit),
            _from_topics(client, query, geo, span),
        )
    ):
        for position, candidate in enumerate(group):
            existing = merged.get(candidate.mid)
            if existing is None:
                merged[candidate.mid] = candidate
                rank[candidate.mid] = (priority, position)
                continue

            # Seen in both indexes, which is the strongest signal available.
            sources = sorted(
                {*existing.source.split("+"), *candidate.source.split("+")}
            )
            merged[candidate.mid] = Candidate(
                mid=candidate.mid,
                name=existing.name or candidate.name,
                description=existing.description or candidate.description,
                source="+".join(sources),
                score=existing.score,
            )

    return sorted(
        merged.values(),
        key=lambda c: (0 if "+" in c.source else 1, *rank[c.mid]),
    )
