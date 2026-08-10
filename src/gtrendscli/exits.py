"""Deterministic exit codes.

| 0 | success                                                    |
| 1 | usage error: bad flags, unparseable dates, clamp violation |
| 2 | API or network error after retries                         |
| 3 | assertion failure, e.g. `entity verify` mismatch           |
| 4 | data-quality warning escalated by `--strict`               |

An agent must be able to tell these apart without reading prose.
"""

from __future__ import annotations

import click

from gtrendscli.api.errors import ApiError


class ApiFailure(click.ClickException):
    """The API refused or could not answer the request."""

    exit_code = 2


class AssertionFailure(click.ClickException):
    """Something the caller asserted turned out not to hold."""

    exit_code = 3


class StrictFailure(click.ClickException):
    """Warnings were raised and `--strict` makes them fatal."""

    exit_code = 4


def guard_api(exc: Exception) -> click.ClickException:
    """Translate a known failure into its exit code, re-raising anything else.

    Only two kinds get translated. An API error is exit 2. A filesystem error
    -- an unwritable archive directory, say -- is a setup problem and so a
    usage error, not an outage; reporting it as an API failure would tell an
    agent to retry something that will never succeed.
    """
    if isinstance(exc, ApiError):
        return ApiFailure(str(exc))

    if isinstance(exc, OSError):
        return click.ClickException(
            f"filesystem error: {exc.strerror or exc}"
            + (f" ({exc.filename})" if exc.filename else "")
        )

    raise exc
