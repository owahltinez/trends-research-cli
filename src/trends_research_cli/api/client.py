"""HTTP transport, retries and raw archiving.

Nothing above this module imports an HTTP library, and no test does either: the
seam is the ``Transport`` protocol, so the client is exercised offline with a
fake and the library choice stays an implementation detail.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple, Protocol

from trends_research_cli.api.endpoints import Endpoint, Params, build_url
from trends_research_cli.api.errors import ApiError, TransportError, diagnose

# Transient statuses worth another attempt. 500 is deliberately absent: this
# API answers a caller error with 500, so retrying would hammer it over a typo.
RETRY_STATUSES = frozenset({429, 502, 503, 504})

MAX_ATTEMPTS = 4
BACKOFF_SECONDS = 1.0

MIN_INTERVAL_SECONDS = 0.5
"""The API is documented as allowing 2 queries per second. Chunked collections
would otherwise burst straight through that, which is our fault, not theirs."""


class Response(NamedTuple):
    """What a transport returns: a status and, on success, a decoded body."""

    status: int
    body: dict[str, Any] | None


class Transport(Protocol):
    """The only thing in the tool that performs network I/O."""

    def get(self, url: str, params: Params) -> Response:
        """Perform one GET, adding whatever credential it holds."""
        ...


class Client:
    """Fetches endpoints, retrying what is worth retrying and archiving all."""

    def __init__(
        self,
        transport: Transport,
        *,
        raw_dir: Path | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
        max_attempts: int = MAX_ATTEMPTS,
        min_interval: float = MIN_INTERVAL_SECONDS,
    ):
        """Wrap a transport, optionally archiving every response to disk."""
        self._transport = transport
        self._raw_dir = raw_dir
        self._sleep = sleep
        self._now = now
        self._max_attempts = max_attempts
        self._min_interval = min_interval
        self._last_request: float | None = None
        self._archived = 0
        self.key_source = "unknown"
        """Where the credential came from. Never the key itself."""

        self.calls: list[dict[str, Any]] = []
        """Every successful call, for the run receipt. Never holds the key."""

    def fetch(self, endpoint: Endpoint, params: Params) -> dict[str, Any]:
        """Return the response body, or raise ``ApiError`` with a diagnosis."""
        return self._request(
            build_url(endpoint),
            params,
            label=endpoint.value,
            explain=lambda status: diagnose(status, endpoint),
        )

    def fetch_url(
        self, url: str, params: Params, *, label: str
    ) -> dict[str, Any]:
        """Fetch a service outside the Trends API, such as `kgsearch`."""
        return self._request(
            url,
            params,
            label=label,
            explain=lambda status: (
                f"{label} failed with status {status}. If this is 403, the "
                f"API may not be enabled on the project; run `gtrends doctor`."
            ),
        )

    def _request(
        self,
        url: str,
        params: Params,
        *,
        label: str,
        explain: Callable[[int], str],
    ) -> dict[str, Any]:
        status = 0
        last_failure = ""

        for attempt in range(self._max_attempts):
            self._throttle()

            # A network failure is transient in the same way a 503 is, so it
            # runs through the same backoff rather than aborting the run.
            try:
                response = self._transport.get(url, params)
            except TransportError as exc:
                last_failure = str(exc)
                if attempt == self._max_attempts - 1:
                    raise ApiError(f"{label}: {exc}") from None
                self._sleep(BACKOFF_SECONDS * 2**attempt)
                continue

            status = response.status

            if status == 200:
                self.calls.append(
                    {
                        "endpoint": label,
                        "url": url,
                        "params": [list(pair) for pair in params],
                        "retrieved_at": datetime.now(UTC).isoformat(),
                    }
                )
                self._archive(label, params, response.body or {})
                return response.body or {}

            if status not in RETRY_STATUSES:
                raise ApiError(explain(status), status=status)

            # Exponential backoff, skipped after the final attempt.
            if attempt < self._max_attempts - 1:
                self._sleep(BACKOFF_SECONDS * 2**attempt)

        raise ApiError(
            f"{label} still failing after {self._max_attempts} attempts "
            f"({last_failure or f'status {status}'}).",
            status=status,
        )

    def _throttle(self) -> None:
        """Hold requests to the documented rate limit."""
        if self._last_request is not None:
            waited = self._now() - self._last_request
            if waited < self._min_interval:
                self._sleep(self._min_interval - waited)

        self._last_request = self._now()

    def _archive(
        self, label: str, params: Params, body: dict[str, Any]
    ) -> None:
        """Write the raw response so a published number stays defensible.

        Parameters are safe to store because the API key is added by the
        transport and never appears in them.
        """
        if self._raw_dir is None:
            return

        self._raw_dir.mkdir(parents=True, exist_ok=True)

        # The counter restarts every process, so a bare index would let one
        # run silently overwrite the evidence of the last. Step past anything
        # already there instead: an archive that loses a previous answer is
        # worse than no archive at all.
        path = self._raw_dir / f"{label}-{self._archived:04d}.json"
        while path.exists():
            self._archived += 1
            path = self._raw_dir / f"{label}-{self._archived:04d}.json"
        path.write_text(
            json.dumps(
                {
                    "endpoint": label,
                    "params": [list(pair) for pair in params],
                    "retrieved_at": datetime.now(UTC).isoformat(),
                    "body": body,
                },
                indent=2,
            )
        )
        self._archived += 1
