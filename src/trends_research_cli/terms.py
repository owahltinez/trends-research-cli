"""Telling entity IDs from free text.

Free text matches strings, so a wrong transliteration returns all zeros —
indistinguishable from a true null. Entity IDs are therefore the default and
free text always warns; the distinction is unambiguous from the prefix, so
nobody has to pass a flag to be understood.
"""

ENTITY_PREFIXES = ("/m/", "/g/")


def is_entity_id(term: str) -> bool:
    """True if the term is a Knowledge Graph entity ID rather than free text."""
    return term.startswith(ENTITY_PREFIXES)


def free_text_warning(terms: list[str]) -> str | None:
    """Warn about any free-text terms, naming them."""
    plain = [term for term in terms if not is_entity_id(term)]
    if not plain:
        return None

    listed = ", ".join(repr(term) for term in plain)
    return (
        f"matching free text ({listed}) rather than an entity: results depend "
        f"on exact spelling and a wrong variant returns zeros that look like a "
        f"real null. Run `gtrends entity find` to get an ID."
    )
