"""Command-line entry point. Groups only — logic lives in `commands/`."""

from __future__ import annotations

from pathlib import Path

import click

from trends_research_cli import __version__
from trends_research_cli.api.client import Client
from trends_research_cli.api.transport import Urllib3Transport
from trends_research_cli.commands.category import categories
from trends_research_cli.commands.check import check
from trends_research_cli.commands.discover import queries, topics
from trends_research_cli.commands.doctor import doctor
from trends_research_cli.commands.entity import entity
from trends_research_cli.commands.guide import guide
from trends_research_cli.commands.series import series
from trends_research_cli.commands.skill import skill
from trends_research_cli.credentials import CredentialsError, resolve_credential

# Click exits 2 for usage errors, which this tool documents as "API error".
# Agents are told to branch on these codes, and misreading a flag mistake as a
# transient API failure invites a pointless retry, so click is brought into
# line rather than the documentation bent around it.
click.UsageError.exit_code = 1


# These blocks need their line breaks kept, which is what Click's \b marker
# does. They live in the epilog rather than the docstring because the marker
# is an ASCII backspace: a docstring holding one has to be non-raw, and a
# non-raw docstring containing a backslash is exactly what the linter objects
# to. An epilog is an ordinary string, so both can be satisfied.
EPILOG = """\b
Run `gtrends doctor` first, and `gtrends guide` for the full manual -- units,
the date rules, the zero caveat and the exit codes, in one place and with no
network needed.

\b
Exit codes: 0 success, 1 usage error (including a date range containing no
whole period), 2 API or network error, 3 assertion failure such as `entity
verify` finding a different name, 4 warnings under --strict."""


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]}, epilog=EPILOG
)
@click.version_option(__version__)
@click.option("--api-key", help="Overrides $TRENDS_API_KEY and .env.")
@click.option(
    "--raw-dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Archive every raw response here, for provenance and re-checking.",
)
@click.pass_context
def main(ctx: click.Context, api_key: str | None, raw_dir: Path | None) -> None:
    """Query the Google Trends Research / Health Trends API.

    Values are absolute probabilities, never rescaled:

        value = P(term | date AND geography) x 10,000,000

    This is the allow-listed research API, not the public Trends site: there
    is no hourly data and no 0-100 index, and access is granted per project.
    A key is requested at https://support.google.com/trends/contact/trends_api
    -- it cannot be created in the Cloud console.
    """
    # Tests inject a prepared client; only build one otherwise.
    if ctx.obj is not None:
        return

    try:
        credential = resolve_credential(api_key)
        client = Client(Urllib3Transport(credential.key), raw_dir=raw_dir)
        client.key_source = credential.source
        ctx.obj = client
    except CredentialsError as exc:
        # Carried rather than raised, so `doctor` can still run and explain it.
        ctx.obj = exc


for command in (
    guide,
    doctor,
    skill,
    categories,
    entity,
    series,
    queries,
    topics,
    check,
):
    main.add_command(command)
