"""Turning useless API errors into actionable ones.

The API answers almost every caller mistake with ``Request contains an invalid
argument`` and no indication of which argument. Rather than pass that through,
each status is mapped to the causes actually observed for that endpoint.
"""

from __future__ import annotations

from gtrendscli.api.endpoints import Endpoint, spec_for


class TransportError(RuntimeError):
    """The request never got an HTTP response: DNS, TLS, timeout, refused.

    Carries only the host, never the URL. urllib3 embeds the full URL --
    including the query string -- in its exception messages, so letting one
    propagate would print the API key to the terminal.
    """


class ApiError(RuntimeError):
    """A request failed and could not be retried.

    Carries the HTTP status so callers branch on the fact rather than on the
    wording of the message.
    """

    def __init__(self, message: str, *, status: int | None = None):
        """Record the message and the status that produced it."""
        super().__init__(message)
        self.status = status


def _bad_request(endpoint: Endpoint) -> str:
    spec = spec_for(endpoint)
    term_param = "terms" if spec.multi_term else "term"
    date_format = "YYYY-MM-DD" if spec.day_granular else "YYYY-MM"

    return (
        f"{endpoint.value} rejected the request's parameters. This endpoint "
        f"wants `{term_param}`, `{spec.date_prefix}.startDate`/`.endDate` as "
        f"{date_format}, and "
        + (
            "`geoRestriction.country` or `.region`"
            if spec.split_geo
            else "`restrictions.geo`"
        )
        + ". An OAuth bearer token also produces this error; the API takes an "
        "API key only."
    )


def _server_error(endpoint: Endpoint) -> str:
    """Name the caller mistakes this API reports as a server error.

    Verified live: both a sub-month range and an unknown category answer 500
    rather than 400, so the likeliest cause is something the caller sent, not
    an outage. Listing only one of them sends people hunting the wrong bug.
    """
    spec = spec_for(endpoint)

    causes = []
    if not spec.day_granular:
        causes.append(
            "a date range shorter than a whole month (widen it to cover at "
            "least one)"
        )
    if spec.date_prefix == "restrictions":
        causes.append(
            "a category id that does not exist -- `--category` is checked "
            "against the bundled taxonomy, but `--category-id` is sent as "
            "given, so confirm it with `gtrends categories --show <id>`"
        )

    if not causes:
        return f"{endpoint.value} returned 500."

    listed = "; or ".join(causes)
    return (
        f"{endpoint.value} returned 500. This endpoint reports caller "
        f"mistakes that way, so the likely cause is {listed}."
    )


def diagnose(status: int, endpoint: Endpoint) -> str:
    """Return a message naming the likely cause of a failed request."""
    if status == 400:
        return _bad_request(endpoint)

    if status in (401, 403):
        return (
            f"{endpoint.value} refused the API key ({status}). The key may be "
            f"invalid, restricted to other referrers, or lack access to this "
            f"API. Run `gtrends doctor`."
        )

    if status == 404:
        return f"{endpoint.value} does not exist at this API version."

    if status >= 500:
        return _server_error(endpoint)

    return f"{endpoint.value} failed with status {status}."
