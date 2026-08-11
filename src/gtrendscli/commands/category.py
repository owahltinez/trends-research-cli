"""`gtrends categories` — browse and resolve the vendored taxonomy.

The taxonomy is bundled rather than fetched: it changed once in the seven
years to 2026, and having it locally means a wrong `--category` costs no
request. It is also a DAG whose parents contain their descendants, so this
command exists mainly to make "what did I just filter to?" answerable before
the request rather than after.
"""

from __future__ import annotations

import json

import click

from gtrendscli import categories as taxonomy
from gtrendscli.categories import CategoryError

VINTAGE_NOTE = (
    "this taxonomy predates about 2012: its newest entries are Blu-Ray "
    "players and DVRs, and it has no category for AI, cryptocurrency, "
    "streaming, electric vehicles or vaping"
)


def _render(entries: list[tuple[int, str]]) -> None:
    width = max((len(str(i)) for i, _ in entries), default=2)
    for identifier, path in entries:
        described = taxonomy.describe(identifier)
        suffix = (
            f"  (+{described.descendants} below)"
            if described.descendants
            else ""
        )
        click.echo(f"{identifier:>{width}}  {path}{suffix}")


@click.command(
    "categories",
    epilog="""Examples:

\b
  gtrends categories --find health
  gtrends categories --show "/Health/Health Conditions"
  gtrends series /m/0cycc --geo US --from 2025-07 --by region \\
      --category "/Health/Health Conditions" """,
)
@click.option(
    "--find", "text", help="List categories whose name contains this."
)
@click.option(
    "--show",
    "path",
    help="Resolve one path or id and report exactly what it selects.",
)
@click.option(
    "--json", "as_json", is_flag=True, help="Machine-readable output."
)
def categories(text: str | None, path: str | None, as_json: bool) -> None:
    """Look up Google Trends categories for `--category`.

    Names are globally unique, so a bare leaf resolves on its own; a full path
    is accepted and is what gets echoed back. A parent includes everything
    beneath it, which `--show` spells out.
    """
    if text and path:
        raise click.UsageError("choose one of --find or --show")

    source, fetched = taxonomy.provenance()

    if path:
        try:
            given = path.strip()
            identifier = (
                int(given)
                if given.lstrip("-").isdigit()
                else taxonomy.resolve(given)
            )
            described = taxonomy.describe(identifier)
        except CategoryError as exc:
            raise click.ClickException(str(exc)) from None

        if as_json:
            click.echo(
                json.dumps(
                    {
                        "id": described.id,
                        "name": described.name,
                        "path": described.path,
                        "all_paths": list(described.all_paths),
                        "descendants": described.descendants,
                        "children": described.child_names,
                        "contained_by": list(described.ancestor_paths),
                        "source": source,
                        "fetched": fetched,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return

        click.echo(f"# {described.id}  {described.path}")
        for extra in described.all_paths[1:]:
            click.echo(f"# also reachable as {extra}")
        if described.ancestor_paths:
            click.echo(
                f"# contained by: {', '.join(described.ancestor_paths)} "
                f"-- results filtered to those overlap this one"
            )
        if described.descendants:
            click.echo(
                f"# selecting it includes {described.descendants} "
                f"sub-categories, starting with: "
                f"{', '.join(described.child_names[:6])}"
            )
        else:
            click.echo("# nothing below it")
        return

    entries = (
        taxonomy.search(text)
        if text
        else sorted((i, taxonomy.describe(i).path) for i in taxonomy.load())
    )

    if as_json:
        click.echo(
            json.dumps(
                {
                    "source": source,
                    "fetched": fetched,
                    "categories": [{"id": i, "path": p} for i, p in entries],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    if not entries:
        click.echo(f"# nothing matches {text!r}", err=True)
        return

    click.echo(f"# vendored from {source}, fetched {fetched}")
    click.echo(f"# note: {VINTAGE_NOTE}")
    _render(entries)
