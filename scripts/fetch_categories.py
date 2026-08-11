# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Regenerate the vendored Google Trends category taxonomy.

Run by hand, review the diff, and ship a release. Stdlib only and carrying its
own PEP 723 metadata, so it runs from a bare checkout with no project
environment.

This is not a build step and there is no runtime equivalent: the taxonomy
gained one category in the seven years to 2026, so a refresh path in the tool
would be a network fetch, a cache and its failure modes in exchange for
something that happens less often than a release.

    uv run scripts/fetch_categories.py

Its newest entries are Blu-Ray players and DVRs, so the vocabulary itself dates
to roughly 2010. The source is the picker behind the public Trends front end,
not the Research API this tool otherwise speaks to.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

SOURCE = "https://trends.google.com/trends/api/explore/pickers/category"
TARGET = (
    Path(__file__).resolve().parents[1]
    / "src/trends_research_cli/data/categories.json"
)

# Google prefixes its JSON responses with an anti-hijacking guard.
GUARD = ")]}'"


def count(node: dict) -> int:
    """Nodes in the tree, counting each appearance of a shared category."""
    return ("id" in node) + sum(count(c) for c in node.get("children") or [])


def main() -> None:
    """Fetch the taxonomy and overwrite the vendored copy."""
    request = urllib.request.Request(
        f"{SOURCE}?hl=en-US&tz=0", headers={"User-Agent": "trends_research_cli"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode()

    tree = json.loads(body.removeprefix(GUARD).lstrip())
    payload = {
        "_source": SOURCE,
        "_fetched": datetime.now(UTC).date().isoformat(),
        "_note": (
            "Category names and IDs from the public Google Trends category "
            "picker. Vendored so `--category` can be resolved and validated "
            "offline. Regenerate with scripts/fetch_categories.py."
        ),
        "tree": tree,
    }

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {TARGET} — {count(tree)} nodes")


if __name__ == "__main__":
    main()
