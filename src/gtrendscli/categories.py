"""The Google Trends category taxonomy, vendored.

Two properties of this taxonomy drive everything here.

It is a **DAG, not a tree**: 231 categories sit at more than one place in it,
so `Animated Films` is reachable through both `Comics & Animation` and
`Movies`. Both paths are real and resolve to the same id.

A parent **contains** its descendants. Verified against the live API: filtering
by `Comics & Animation` returns the traffic of `Anime & Manga` beneath it. So a
caller choosing a parent has to be told what they swept in, and comparing a
category against its own ancestor compares a set with a superset of itself.

The data is vendored rather than fetched because it barely moves — one addition
in the seven years to 2026 — and because validating a category locally means a
wrong one costs no request. Regenerate with `scripts/fetch_categories.py`.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from functools import cache
from importlib import resources

ALL_CATEGORIES = 0
"""The root, literally named "All categories". Sending it equals
sending nothing."""

SEPARATOR = "/"


class CategoryError(ValueError):
    """A category could not be resolved against the vendored taxonomy."""


@dataclass(frozen=True)
class Category:
    """A resolved category, and what choosing it actually selects."""

    id: int
    name: str
    path: str
    """Canonical fully-qualified form, leading separator included."""

    all_paths: tuple[str, ...]
    """Every route to this category; more than one for 231 of them."""

    descendants: int
    child_names: list[str]
    ancestors: frozenset[int]
    ancestor_paths: tuple[str, ...]
    """Every category containing this one, nearest first. Results filtered
    to those are not independent of results filtered to this."""

    def is_within(self, other: int) -> bool:
        """Is this category contained by `other`? Overlap, not independence."""
        return other in self.ancestors


@cache
def _taxonomy() -> dict:
    """The taxonomy bundled with this release.

    There is deliberately no refresh path. The taxonomy gained one category in
    the seven years to 2026, so a network fetch, a cache and its failure modes
    would be a lot of machinery for an event that happens less often than a
    release. When Google does change it, regenerate with
    `scripts/fetch_categories.py` and ship a new version.
    """
    source = resources.files("gtrendscli") / "data" / "categories.json"
    return json.loads(source.read_text(encoding="utf-8"))


@cache
def provenance() -> tuple[str, str]:
    """Where the bundled copy came from, and when."""
    data = _taxonomy()
    return data["_source"], data["_fetched"]


@dataclass(frozen=True)
class _Node:
    name: str
    paths: tuple[str, ...]
    children: tuple[tuple[int, str], ...]
    descendants: int
    ancestors: frozenset[int]


@cache
def _index() -> dict[int, _Node]:
    """Flatten the DAG once, keeping every route and the containment closure."""
    paths: dict[int, list[str]] = {}
    ancestors: dict[int, set[int]] = {}
    children: dict[int, list[tuple[int, str]]] = {}
    names: dict[int, str] = {}

    def walk(
        node: dict, trail: tuple[str, ...], above: tuple[int, ...]
    ) -> set[int]:
        identifier, name = node.get("id"), node.get("name", "")
        here = trail + ((name,) if name else ())

        below: set[int] = set()
        kids = node.get("children") or []

        if identifier is not None:
            names[identifier] = name
            # The root is not part of a path: /Health, never
            # /All categories/Health.
            paths.setdefault(identifier, []).append(
                SEPARATOR + SEPARATOR.join(here[1:])
                if len(here) > 1
                else SEPARATOR
            )
            ancestors.setdefault(identifier, set()).update(above)
            children.setdefault(identifier, [])
            children[identifier].extend(
                (c["id"], c.get("name", "")) for c in kids if "id" in c
            )
            above = above + (identifier,)

        for child in kids:
            below |= walk(child, here, above)

        if identifier is not None:
            below.add(identifier)

        return below

    tree = _taxonomy()["tree"]
    walk(tree, (), ())

    # Descendant counts need a second pass, since a node can be visited twice.
    counts: dict[int, int] = {}

    def count(identifier: int, seen: frozenset[int] = frozenset()) -> int:
        if identifier in counts:
            return counts[identifier]
        total = 0
        for child, _ in children.get(identifier, []):
            if child not in seen:
                total += 1 + count(child, seen | {identifier})
        counts[identifier] = total
        return total

    return {
        identifier: _Node(
            name=names[identifier],
            paths=tuple(dict.fromkeys(paths[identifier])),
            children=tuple(dict.fromkeys(children.get(identifier, []))),
            descendants=count(identifier),
            ancestors=frozenset(ancestors.get(identifier, set())),
        )
        for identifier in names
    }


def load() -> dict[int, str]:
    """Every category id and its name."""
    return {identifier: node.name for identifier, node in _index().items()}


def paths_for(identifier: int) -> list[str]:
    """Every route to a category. More than one for 231 of them."""
    return list(_index()[identifier].paths)


def children_of(identifier: int) -> list[tuple[int, str]]:
    """The immediate level below a category."""
    return list(_index()[identifier].children)


def describe(identifier: int) -> Category:
    """Resolve an id into what selecting it actually means."""
    index = _index()
    if identifier not in index:
        _, fetched = provenance()
        raise CategoryError(
            f"category {identifier} is not in the taxonomy bundled with this "
            f"release (fetched {fetched}). The API answers an unknown "
            f"category with an opaque 500, so it is refused here instead. "
            f"Look one up with `gtrends categories --find <text>`; if Google "
            f"has added it since, upgrade gtrendscli."
        )

    node = index[identifier]

    # Nearest first: the deepest containing category is the most useful to
    # name, and the root ("All categories") is not worth mentioning.
    containing = sorted(
        (a for a in node.ancestors if a != ALL_CATEGORIES),
        key=lambda a: -len(index[a].paths[0]),
    )

    return Category(
        id=identifier,
        name=node.name,
        path=node.paths[0],
        all_paths=node.paths,
        descendants=node.descendants,
        child_names=[name for _, name in node.children],
        ancestors=node.ancestors,
        ancestor_paths=tuple(index[a].paths[0] for a in containing),
    )


def _normalise(text: str) -> str:
    """`  /Health / Health Conditions ` and `health conditions` are the same."""
    parts = [part.strip() for part in text.strip().split(SEPARATOR)]
    return SEPARATOR.join(part for part in parts if part).casefold()


def resolve(text: str) -> int:
    """Resolve a path or bare name to a category id.

    A leading separator is accepted but never required: names are globally
    unique in this taxonomy, so a bare leaf resolves on its own. Anchoring
    still matters if that ever stops being true, so it is honoured.
    """
    wanted = _normalise(text)

    # A bare separator is the root, which means "no filter".
    if not wanted:
        return ALL_CATEGORIES

    anchored = text.strip().startswith(SEPARATOR)
    index = _index()

    for identifier, node in index.items():
        for path in node.paths:
            candidate = _normalise(path)
            if candidate == wanted:
                return identifier
            if not anchored and candidate.endswith(SEPARATOR + wanted):
                return identifier

    raise CategoryError(_unknown(text))


def _unknown(text: str) -> str:
    leaf = text.strip().strip(SEPARATOR).split(SEPARATOR)[-1].strip()
    names = {node.name: identifier for identifier, node in _index().items()}
    near = difflib.get_close_matches(leaf, names, n=3, cutoff=0.6)

    hint = (
        f" Did you mean {', '.join(near)}?"
        if near
        else " Run `gtrends categories --find <text>` to look one up."
    )
    return f"no category matches {text!r}.{hint}"


def search(text: str) -> list[tuple[int, str]]:
    """Find categories whose name contains `text`, with canonical paths."""
    wanted = text.casefold()
    return [
        (identifier, node.paths[0])
        for identifier, node in sorted(_index().items())
        if wanted in node.name.casefold()
    ]
