"""Sharing a client, or a credentials failure, across commands.

`doctor` must run and explain itself when there is no usable key, so a missing
credential cannot be fatal at group level. It is carried instead, and every
other command turns it into a clean error.
"""

from __future__ import annotations

import click

from trends_research_cli.api.client import Client
from trends_research_cli.credentials import CredentialsError


def require_client(obj: object) -> Client:
    """Return the client, or fail cleanly if credentials could not be found."""
    if isinstance(obj, CredentialsError):
        raise click.ClickException(str(obj))

    if obj is None:
        raise click.ClickException("no API client available")

    return obj  # type: ignore[return-value]
