"""Per-endpoint parameter families.

The Trends API spells the same concepts differently on almost every endpoint,
and supplying the wrong spelling returns a bare ``400 INVALID_ARGUMENT`` (or, on
the month-granular endpoints, a ``500``) with no indication of what was wrong.
Callers therefore never build parameters themselves; they name an endpoint and
pass plain values.

Four properties vary independently, and nothing about an endpoint's name
predicts them — ``regions`` uses restriction-style parameter names yet accepts
full dates, while its siblings reject a sub-month range. So they are recorded
as a table, verified against the live API by ``tests/live/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from trends_research_cli.dates import DateRange, Interval

BASE_URL = "https://www.googleapis.com/trends/v1beta"

Params = list[tuple[str, str]]

MAX_TERMS = 30
"""Documented ceiling on `terms` per request."""

# The API still calls Shopping by its 2006 name. Web search is the empty
# string, which is how the picker sends "no property filter".
PROPERTIES = {
    "web": "",
    "news": "news",
    "images": "images",
    "youtube": "youtube",
    "shopping": "froogle",
}


class Endpoint(StrEnum):
    """Every endpoint the tool talks to. Only ``regions`` is documented."""

    TIMELINES = "timelinesForHealth"
    REGIONS = "regions"
    TOP_QUERIES = "topQueries"
    RISING_QUERIES = "risingQueries"
    TOP_TOPICS = "topTopics"
    RISING_TOPICS = "risingTopics"
    GRAPH = "graph"


@dataclass(frozen=True)
class Spec:
    """How one endpoint spells its parameters."""

    multi_term: bool
    """Accepts many terms as ``terms``; otherwise exactly one as ``term``."""

    date_prefix: str
    """``time`` or ``restrictions``, prefixing ``.startDate`` / ``.endDate``."""

    day_granular: bool
    """Takes ``YYYY-MM-DD``; otherwise ``YYYY-MM``."""

    split_geo: bool
    """Splits geo into ``geoRestriction.country`` / ``.region`` by level."""

    takes_interval: bool
    """Requires ``timelineResolution``."""


_SPECS: dict[Endpoint, Spec] = {
    Endpoint.TIMELINES: Spec(
        multi_term=True,
        date_prefix="time",
        day_granular=True,
        split_geo=True,
        takes_interval=True,
    ),
    # Day-granular despite the restriction-style names; confirmed by probing a
    # five-day range against a whole month and getting different answers.
    Endpoint.REGIONS: Spec(
        multi_term=False,
        date_prefix="restrictions",
        day_granular=True,
        split_geo=False,
        takes_interval=False,
    ),
    Endpoint.TOP_QUERIES: Spec(False, "restrictions", False, False, False),
    Endpoint.RISING_QUERIES: Spec(False, "restrictions", False, False, False),
    Endpoint.TOP_TOPICS: Spec(False, "restrictions", False, False, False),
    Endpoint.RISING_TOPICS: Spec(False, "restrictions", False, False, False),
    Endpoint.GRAPH: Spec(True, "restrictions", False, False, False),
}


def build_url(endpoint: Endpoint) -> str:
    """Return the full URL for an endpoint."""
    return f"{BASE_URL}/{endpoint.value}"


def spec_for(endpoint: Endpoint) -> Spec:
    """Return the parameter spelling rules for an endpoint."""
    return _SPECS[endpoint]


def _term_params(endpoint: Endpoint, spec: Spec, terms: list[str]) -> Params:
    if not terms:
        raise ValueError(f"{endpoint.value} needs at least one term")

    # The API answers a blank term with a bare 400. Refusing locally costs
    # nothing and keeps the quota for requests that could have worked.
    blank = [index for index, term in enumerate(terms) if not term.strip()]
    if blank:
        raise ValueError(
            f"term {blank[0] + 1} is blank; give an entity ID (/m/... or "
            f"/g/...) or a search string"
        )

    if spec.multi_term:
        if len(terms) > MAX_TERMS:
            raise ValueError(
                f"{endpoint.value} accepts at most {MAX_TERMS} terms, got "
                f"{len(terms)}; split the request"
            )
        return [("terms", term) for term in terms]

    # Several terms where the API accepts one yields a bare 400, so refuse
    # locally with a message that names the actual constraint.
    if len(terms) > 1:
        raise ValueError(
            f"{endpoint.value} accepts only one term at a time, got "
            f"{len(terms)}; call it once per term"
        )
    return [("term", terms[0])]


def _date_params(spec: Spec, span: DateRange) -> Params:
    # Month-granular endpoints reject a full date with a 500. The caller has
    # already clamped to whole months, so truncating cannot widen the window.
    fmt = (
        (lambda d: d.isoformat())
        if spec.day_granular
        else (lambda d: d.strftime("%Y-%m"))
    )
    return [
        (f"{spec.date_prefix}.startDate", fmt(span.start)),
        (f"{spec.date_prefix}.endDate", fmt(span.end)),
    ]


def _geo_params(spec: Spec, geo: str) -> Params:
    if not geo.strip():
        raise ValueError(
            "geo is blank; give a country (US), a region (US-NY) or a "
            "Nielsen DMA number (501)"
        )

    # A newline would forge a comment line in the output header, and no real
    # geo code contains one.
    if any(ord(char) < 32 for char in geo):
        raise ValueError(f"geo contains a control character: {geo!r}")

    if not spec.split_geo:
        return [("restrictions.geo", geo)]

    # Three keys by level, and the wrong one is rejected without explanation.
    # A bare number is a Nielsen DMA -- a US media market, e.g. 501 for New
    # York -- which is neither a country nor a region code.
    if geo.isdigit():
        key = "geoRestriction.dma"
    elif "-" in geo:
        key = "geoRestriction.region"
    else:
        key = "geoRestriction.country"

    return [(key, geo)]


def _filter_params(
    endpoint: Endpoint,
    spec: Spec,
    category: int | None,
    trends_property: str | None,
) -> Params:
    """Category and property, which only the restriction family honours.

    `timelinesForHealth` accepts both and silently ignores them -- verified
    live: identical values for every category and property, including ids that
    return 500 elsewhere. Passing them there would answer a filtered question
    with unfiltered data, so it is refused rather than forwarded.
    """
    asked = {"--category": category, "--property": trends_property}
    given = [flag for flag, value in asked.items() if value is not None]

    if not given:
        return []

    if spec.date_prefix != "restrictions":
        raise ValueError(
            f"{endpoint.value} ignores {' and '.join(given)} -- it accepts "
            f"them and returns unfiltered data, so this tool refuses them "
            f"rather than report a filter that was never applied"
        )

    params: Params = []
    if category is not None:
        params.append(("restrictions.category", str(category)))
    if trends_property is not None:
        if trends_property not in PROPERTIES:
            raise ValueError(
                f"unknown property {trends_property!r}; choose one of "
                f"{', '.join(sorted(PROPERTIES))}"
            )
        params.append(("restrictions.property", PROPERTIES[trends_property]))

    return params


def build_params(
    endpoint: Endpoint,
    *,
    terms: list[str],
    geo: str,
    span: DateRange,
    interval: Interval | None = None,
    category: int | None = None,
    trends_property: str | None = None,
) -> Params:
    """Build the query parameters for one endpoint call.

    Returns pairs rather than a mapping because ``terms`` repeats. The API key
    is deliberately absent: it is injected by the transport, so these parameters
    are safe to log, archive and put in a run receipt.
    """
    spec = _SPECS[endpoint]
    params = _term_params(endpoint, spec, terms) + _date_params(spec, span)

    if spec.takes_interval:
        if interval is None:
            raise ValueError(f"{endpoint.value} requires an interval")
        params.append(("timelineResolution", interval.value))

    return (
        params
        + _geo_params(spec, geo)
        + _filter_params(endpoint, spec, category, trends_property)
    )
