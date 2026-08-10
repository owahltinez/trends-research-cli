"""`gtrends skill` — put the packaged Agent Skill where agents will find it.

Installing the CLI is not enough: agents discover skills by scanning specific
directories, and those directories are per-tool. `~/.agents/skills` is the
emerging cross-tool location, but several tools only read their own. So rather
than guess, `install` writes to the shared location and reports every tool
directory it can see, with the command to cover those too.
"""

from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path

import click

SKILL_NAME = "gtrends"

# The tool-agnostic location. Read by Gemini CLI and others; a reasonable
# default even where a tool also keeps its own directory.
SHARED_DIR = Path(".agents") / "skills"

# Per-tool directories, keyed by the marker that shows the tool is installed.
TOOL_DIRS: dict[str, tuple[Path, Path]] = {
    "Claude Code": (Path(".claude"), Path(".claude") / "skills"),
    "Gemini CLI": (Path(".gemini"), Path(".gemini") / "skills"),
    "Antigravity": (Path(".gemini"), Path(".gemini") / "config" / "skills"),
    "Cursor": (Path(".cursor"), Path(".cursor") / "skills"),
}

TARGET_HELP = {
    "to": (
        f"A skills directory to act on. The skill lives in a `{SKILL_NAME}` "
        "subdirectory of it, as the spec requires."
    ),
    "dry_run": "Print what would happen without touching the filesystem.",
}


def packaged_skill() -> Path:
    """Locate SKILL.md, whether running from a wheel or a source checkout.

    It is authored at the repository root, where it is visible, and mapped into
    the package at build time. Both locations have to work: the wheel path for
    real installs, the repository path when running from source.
    """
    packaged = Path(
        str(resources.files("gtrendscli") / "skills" / SKILL_NAME / "SKILL.md")
    )
    if packaged.is_file():
        return packaged

    checkout = Path(__file__).resolve().parents[3] / "SKILL.md"
    if checkout.is_file():
        return checkout

    raise click.ClickException(
        f"SKILL.md not found at {packaged} or {checkout}"
    )


def detected_tools(home: Path) -> dict[str, Path]:
    """Return skills directories for the agent tools present on this machine."""
    return {
        name: home / skills
        for name, (marker, skills) in TOOL_DIRS.items()
        if (home / marker).is_dir()
    }


def _primary_target(destination: Path | None, home: Path) -> Path:
    """The one location acted on when no sweep was requested.

    A repository-scoped install is just `--to .agents/skills`, so it needs no
    flag of its own.
    """
    if destination is not None:
        return destination / SKILL_NAME
    return home / SHARED_DIR / SKILL_NAME


def _is_our_skill(target: Path) -> bool:
    """Does this directory actually hold the skill we installed?

    A broken symlink counts. `--link` into a `uvx` environment dies on
    `uv cache prune`, and refusing to clean up exactly that wreckage would be
    perverse -- the directory is still one this tool created.
    """
    manifest = target / "SKILL.md"
    if manifest.is_symlink() and not manifest.exists():
        return True

    if not manifest.is_file():
        return False

    # Unreadable or not text: not something this tool wrote, and certainly not
    # something to delete on the strength of a guess.
    try:
        return f"name: {SKILL_NAME}" in manifest.read_text(errors="replace")
    except OSError:
        return False


def _remove(target: Path) -> None:
    if target.is_symlink() or target.is_file():
        target.unlink()
    else:
        shutil.rmtree(target)


def _place(source: Path, target: Path, *, link: bool, force: bool) -> str:
    """Place SKILL.md into a skill directory of its own.

    Copying is the default because a link points into the environment this CLI
    was installed into: run under `uvx`, that is a prunable cache, so the skill
    works today and vanishes after `uv cache prune`. Copying costs a stale
    skill after an upgrade, which is cheap here -- the skill is a router, and
    the manual it routes to (`gtrends guide`) ships in the binary.
    """
    if target.exists() or target.is_symlink():
        # `--force` licenses replacing *this* skill, never whatever happens to
        # sit at a mistyped `--to`. Deleting a directory tree is not something
        # to do on the strength of its name.
        if not _is_our_skill(target):
            raise click.ClickException(
                f"{target} exists and does not contain the {SKILL_NAME} "
                f"skill; refusing to replace it. Remove it by hand if that is "
                f"really intended."
            )
        if not force:
            raise click.ClickException(
                f"{target} already exists; pass --force to replace it"
            )
        _remove(target)

    # The directory is always real, and named for the skill as the spec
    # requires; only its contents are ever linked.
    target.mkdir(parents=True, exist_ok=True)
    manifest = target / "SKILL.md"

    if link:
        try:
            manifest.symlink_to(source)
        except OSError as exc:
            # Windows needs Developer Mode or admin rights for symlinks. A
            # copy is a worse answer than a link but a much better one than
            # a traceback.
            click.echo(f"# symlink failed ({exc}); copying instead", err=True)
        else:
            return f"linked  {manifest} -> {source}"

    shutil.copy2(source, manifest)
    return f"copied  {target}"


@click.group()
def skill() -> None:
    """Install the packaged Agent Skill so agents can discover this tool."""


@skill.command(
    "install",
    epilog="""Examples:

\b
  gtrends skill install                  # ~/.agents/skills (cross-tool)
  gtrends skill install --all            # plus every detected tool
  gtrends skill install --to ~/.claude/skills
  gtrends skill install --to .agents/skills   # this repository only
  gtrends skill install --link --force   # track package upgrades""",
)
@click.option(
    "--to",
    "destination",
    type=click.Path(file_okay=False, path_type=Path),
    help=TARGET_HELP["to"],
)
@click.option(
    "--all",
    "every",
    is_flag=True,
    help="Also install into every detected tool's own skills directory.",
)
@click.option(
    "--link",
    is_flag=True,
    help="Symlink instead of copying, so package upgrades take effect "
    "immediately. Only safe for a durable install and a private skills "
    "directory: a link into a `uvx` environment dies on `uv cache prune`, and "
    "one committed to a repository is broken for everyone else. Re-running "
    "install --force is the portable way to refresh.",
)
@click.option("--force", is_flag=True, help="Replace an existing installation.")
@click.option("--dry-run", is_flag=True, help=TARGET_HELP["dry_run"])
def install_command(
    destination: Path | None,
    every: bool,
    link: bool,
    force: bool,
    dry_run: bool,
) -> None:
    """Install the Agent Skill into an agent's skills directory.

    With no options this installs into ~/.agents/skills, the cross-tool
    location, and reports any tool-specific directories it found so you can
    add them with --all.
    """
    source = packaged_skill()

    home = Path.home()
    targets = [_primary_target(destination, home)]

    found = detected_tools(home)
    if every:
        targets += [directory / SKILL_NAME for directory in found.values()]

    for target in targets:
        if dry_run:
            # Predict what the real run would do, including its refusals: a
            # dry run that promises a success the command would decline is
            # worse than no dry run.
            if (target.exists() or target.is_symlink()) and not _is_our_skill(
                target
            ):
                click.echo(
                    f"would REFUSE   {target}: not the {SKILL_NAME} skill"
                )
            elif target.exists() and not force:
                click.echo(f"would REFUSE   {target}: exists, needs --force")
            else:
                click.echo(f"would install  {target}")
            continue
        try:
            click.echo(_place(source, target, link=link, force=force))
        except OSError as exc:
            raise click.ClickException(
                f"could not install into {target}: {exc.strerror or exc}"
            ) from None

    # Naming the alternatives beats silently installing into someone's home
    # directory four times over.
    if found and not every and destination is None:
        click.echo()
        click.echo("# also found tool-specific skills directories:")
        for name, directory in found.items():
            click.echo(f"#   {name}: {directory / SKILL_NAME}")
        click.echo("# install into those too with: gtrends skill install --all")


@skill.command(
    "uninstall",
    epilog="""Examples:

\b
  gtrends skill uninstall                # ~/.agents/skills
  gtrends skill uninstall --all          # every known location
  gtrends skill uninstall --to ~/.claude/skills
  gtrends skill uninstall --to .agents/skills""",
)
@click.option(
    "--to",
    "destination",
    type=click.Path(file_okay=False, path_type=Path),
    help=TARGET_HELP["to"],
)
@click.option(
    "--all",
    "every",
    is_flag=True,
    help="Sweep every known location, whether or not the tool is still "
    "installed. Missing ones are skipped quietly.",
)
@click.option("--dry-run", is_flag=True, help=TARGET_HELP["dry_run"])
def uninstall_command(
    destination: Path | None, every: bool, dry_run: bool
) -> None:
    """Remove the Agent Skill from an agent's skills directory.

    Only ever removes a directory that actually holds this skill, so pointing
    --to somewhere unexpected fails rather than deleting someone's work.
    """
    home = Path.home()
    targets = [_primary_target(destination, home)]

    # Sweeping is for cleanup, so it covers every known location rather than
    # only the tools still present: an uninstalled tool can leave a skill
    # behind, and that is exactly what needs removing.
    if every:
        targets += [
            home / skills / SKILL_NAME for _, skills in TOOL_DIRS.values()
        ]

    removed = 0
    for target in dict.fromkeys(targets):
        if not target.exists() and not target.is_symlink():
            continue

        if not _is_our_skill(target):
            raise click.ClickException(
                f"{target} does not contain the {SKILL_NAME} skill; refusing "
                f"to delete it. Remove it by hand if that is really intended."
            )

        if dry_run:
            click.echo(f"would remove  {target}")
        else:
            try:
                _remove(target)
            except OSError as exc:
                raise click.ClickException(
                    f"could not remove {target}: {exc.strerror or exc}"
                ) from None
            click.echo(f"removed  {target}")
        removed += 1

    if not removed:
        click.echo("nothing to remove")
