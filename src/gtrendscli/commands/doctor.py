"""`gtrends doctor` — is my setup working?.

The API is allow-listed per project, and an un-allow-listed project fails in a
way that looks exactly like a malformed request. Most people who install this
cannot use it on the first try, so telling them precisely why is the difference
between a usable tool and one they bounce off.
"""

from __future__ import annotations

import json
from datetime import timedelta

import click

from gtrendscli.api.client import Client
from gtrendscli.api.endpoints import Endpoint, build_params
from gtrendscli.api.errors import ApiError
from gtrendscli.api.kgsearch import search
from gtrendscli.credentials import CredentialsError
from gtrendscli.dates import DateRange, today_utc

ACCESS_URL = "https://support.google.com/trends/contact/trends_api"


def _probe_trends(client: Client) -> tuple[bool, str]:
    """Call the one documented endpoint, which cannot be malformed."""
    today = today_utc()
    span = DateRange(today - timedelta(days=60), today - timedelta(days=30))

    try:
        client.fetch(
            Endpoint.REGIONS,
            build_params(
                Endpoint.REGIONS, terms=["influenza"], geo="US", span=span
            ),
        )
    except ApiError as exc:
        # This call is known-valid, so a rejection is about access, not shape.
        if exc.status == 400:
            return False, (
                "the request was rejected although it is known-valid. Either "
                "the project is not allow-listed for this API, or an OAuth "
                f"token was supplied instead of an API key. Request access at "
                f"{ACCESS_URL}"
            )
        if exc.status in (401, 403):
            return False, (
                "the key was refused. It may be invalid, restricted to other "
                "referrers, or lack access to this API."
            )
        return False, str(exc)

    return True, "reachable, and this project is allow-listed"


def _probe_kgsearch(client: Client) -> tuple[bool, str]:
    try:
        search(client, "influenza", limit=1)
    except ApiError as exc:
        return False, (
            f"unavailable ({exc}). `entity find` needs the Knowledge Graph "
            f"Search API enabled on the same project."
        )

    return True, "reachable, Knowledge Graph Search API is enabled"


@click.command(
    epilog="Example:\n\n  gtrends doctor --json\n\n"
    "Run this before anything else. Exits 1 if any check fails.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Machine-readable: {ok, checks[{name, ok, detail}]}.",
)
@click.pass_obj
def doctor(obj, as_json: bool) -> None:
    """Check credentials and API access, and explain any failure."""
    checks: list[tuple[str, bool, str]] = []

    if isinstance(obj, CredentialsError):
        checks.append(("credentials", False, str(obj)))
    else:
        source = getattr(obj, "key_source", "unknown")
        checks.append(("credentials", True, f"key found via {source}"))
        checks.append(("trends api", *_probe_trends(obj)))
        checks.append(("kgsearch", *_probe_kgsearch(obj)))

    if as_json:
        click.echo(
            json.dumps(
                {
                    "ok": all(ok for _, ok, _ in checks),
                    "checks": [
                        {"name": name, "ok": ok, "detail": detail}
                        for name, ok, detail in checks
                    ],
                },
                indent=2,
            )
        )
    else:
        for name, ok, detail in checks:
            click.echo(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")

    if not all(ok for _, ok, _ in checks):
        raise click.exceptions.Exit(1)
