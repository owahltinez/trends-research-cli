"""Output flags shared by every command that returns records."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import click

from trends_research_cli import helptext
from trends_research_cli.output.result import (
    Result,
    to_csv,
    to_json,
    to_plain,
    to_text,
    write_parquet,
)


def output_options(command):
    """Attach the shared output flags to a command."""
    for option in reversed(
        [
            click.option("--json", "as_json", is_flag=True, help=helptext.JSON),
            click.option("--csv", "as_csv", is_flag=True, help="Tidy CSV."),
            click.option(
                "--plain",
                "as_plain",
                is_flag=True,
                help=helptext.PLAIN,
            ),
            click.option(
                "--parquet",
                type=click.Path(dir_okay=False, path_type=Path),
                help="Write tidy Parquet to this path.",
            ),
            click.option(
                "--receipt",
                type=click.Path(dir_okay=False, path_type=Path),
                help="Write a run receipt: every call made, and every warning.",
            ),
            click.option(
                "--strict",
                is_flag=True,
                help="Exit 4 if any warning was raised, e.g. a clamped window.",
            ),
        ]
    ):
        command = option(command)
    return command


def write_receipt(result: Result, client, path: Path) -> None:
    """Record how a number was obtained, so it stays defensible later."""
    path.write_text(
        json.dumps(
            {
                "meta": result.meta,
                "warnings": result.warnings,
                "written_at": datetime.now(UTC).isoformat(),
                "calls": getattr(client, "calls", []),
                "record_count": len(result.records),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def emit(
    result: Result,
    *,
    client=None,
    as_json: bool = False,
    as_csv: bool = False,
    as_plain: bool = False,
    parquet: Path | None = None,
    receipt: Path | None = None,
    strict: bool = False,
) -> None:
    """Render a result in whichever format was asked for."""
    del strict  # handled by the caller, which owns the exit code
    del receipt  # written by the caller after the data is out

    # Silently picking one would send a pipeline a format it did not ask for.
    chosen = [
        name
        for name, on in (
            ("--json", as_json),
            ("--csv", as_csv),
            ("--plain", as_plain),
        )
        if on
    ]
    if len(chosen) > 1:
        raise click.UsageError(
            f"choose one output format, got {' '.join(chosen)}"
        )

    if parquet is not None:
        # A missing optional extra or an unwritable path is a setup problem,
        # not a bug.
        try:
            write_parquet(result, parquet)
        except RuntimeError as exc:
            raise click.ClickException(str(exc)) from exc
        except OSError as exc:
            raise click.ClickException(
                f"could not write {parquet}: {exc.strerror or exc}"
            ) from None

    if as_json:
        click.echo(to_json(result))
    elif as_csv:
        click.echo(to_csv(result), nl=False)
    elif as_plain:
        # stdout stays bare so the output pipes cleanly; the caveats go to
        # stderr rather than nowhere. Dropping them would make the composable
        # mode the only one that hides a clamped window or a censored series.
        click.echo(to_plain(result))
        _echo_caveats(result)
    elif parquet is None:
        click.echo(to_text(result))
    else:
        # Writing a file is not a reason to swallow the caveats: a silent
        # exit 0 on a clamped or censored series is the failure this tool
        # exists to prevent.
        click.echo(f"wrote {parquet}", err=True)
        _echo_caveats(result)


def _echo_caveats(result: Result) -> None:
    for warning in result.warnings:
        click.echo(f"# warning: {warning}", err=True)
    for note in result.notes:
        click.echo(f"# note: {note}", err=True)


def write_receipt_or_warn(
    result: Result, client, receipt: Path | None
) -> str | None:
    """Write the run receipt after the data has been delivered.

    Losing a receipt is bad; losing the data because the receipt could not be
    written would be worse, since the API quota has already been spent. So this
    runs last and degrades to a warning -- which is returned, not just printed,
    so `--strict` can escalate it like any other.
    """
    if receipt is None:
        return None

    try:
        write_receipt(result, client, receipt)
    except OSError as exc:
        warning = f"could not write receipt {receipt}: {exc.strerror or exc}"
        click.echo(f"# warning: {warning}", err=True)
        return warning

    return None
