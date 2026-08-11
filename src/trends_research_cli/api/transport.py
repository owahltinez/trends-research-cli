"""The one place the tool performs network I/O.

`urllib3` rather than a higher-level client: the tool makes plain authenticated
GETs, and the only non-trivial thing it needs is connection pooling. Retry and
backoff live in ``client.py`` because the retry *policy* here is unusual — this
API reports caller errors as 500s.
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

import urllib3

from trends_research_cli.api.client import Response
from trends_research_cli.api.endpoints import Params
from trends_research_cli.api.errors import TransportError


class Urllib3Transport:
    """Adds the API key and performs the request.

    The key lives here and nowhere else, so parameters stay safe to log,
    archive and put in a run receipt. It is sent as a header rather than a
    query parameter: urllib3 puts the request URL into its exception messages,
    so a key in the query string ends up in any traceback a network failure
    produces.
    """

    def __init__(self, api_key: str, *, timeout: float = 30.0):
        """Hold the key and a pooled connection for the API host."""
        self._api_key = api_key
        self._pool = urllib3.PoolManager(timeout=timeout)

    def get(self, url: str, params: Params) -> Response:
        """Perform one authenticated GET."""
        try:
            response = self._pool.request(
                "GET",
                url,
                fields=list(params),
                headers={"x-goog-api-key": self._api_key},
            )
        except urllib3.exceptions.HTTPError as exc:
            # Report the host and the failure kind only. The exception's own
            # message contains the full URL, which is why it is not reused.
            raise TransportError(
                f"could not reach {urlsplit(url).netloc}: {type(exc).__name__}"
            ) from None

        # A non-200 body is an error envelope, not data; `client.py` diagnoses
        # the status rather than trusting whatever the API said about it.
        if response.status != 200:
            return Response(response.status, None)

        # A captive portal or proxy can answer 200 with HTML. That is a
        # transport failure, not data, and must not surface as a decode error.
        try:
            return Response(response.status, json.loads(response.data))
        except ValueError:
            raise TransportError(
                f"{urlsplit(url).netloc} returned a 200 that is not JSON; "
                f"a proxy or captive portal may be intercepting the request"
            ) from None
