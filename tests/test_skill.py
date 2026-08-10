"""The packaged Agent Skill must stay valid and stay thin.

SKILL.md is an open standard (Anthropic, now under the Linux Foundation's
Agentic AI Foundation) read by Claude Code, Codex, Cursor, Gemini CLI, Copilot
and others. Agents load only `name` and `description` at discovery, so those
two fields decide whether the skill is ever opened at all.
"""

import re
from pathlib import Path

import pytest
import tomllib
from click.testing import CliRunner

from gtrendscli.cli import main
from gtrendscli.commands.skill import SKILL_NAME, packaged_skill

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "SKILL.md"

FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)

# Defined by the standard; runtimes ignore keys they do not recognise, so an
# unknown key here is more likely a typo than an intentional extension.
STANDARD_KEYS = {
    "name",
    "description",
    "license",
    "allowed-tools",
    "metadata",
    "compatibility",
}


@pytest.fixture(scope="module")
def parts() -> tuple[dict, str]:
    text = SKILL.read_text()
    match = FRONTMATTER.match(text)
    assert match, "frontmatter must start at byte 0 and be delimited by ---"

    # The frontmatter is YAML, but the subset used here is TOML-compatible once
    # quoted, and this keeps the test suite free of a YAML dependency.
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()

    return fields, text[match.end() :]


def test_the_required_fields_are_present(parts):
    fields, _ = parts

    assert fields.get("name"), "name is required"
    assert fields.get("description"), "description is required"


def test_only_standard_keys_are_used(parts):
    fields, _ = parts

    assert set(fields) <= STANDARD_KEYS, (
        f"non-standard frontmatter keys: {set(fields) - STANDARD_KEYS}"
    )


def test_the_name_meets_every_spec_constraint(parts):
    fields, _ = parts
    name = fields["name"]

    assert 1 <= len(name) <= 64
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name), (
        "lowercase alphanumerics and single hyphens only, no leading, "
        "trailing or consecutive hyphens"
    )
    assert "--" not in name


def test_the_installed_directory_will_match_the_name(parts):
    """The spec constrains where the skill is *installed*, not where it is
    authored: `skill install` always creates a directory named for the skill,
    so the file can live at the repository root where it is visible."""
    fields, _ = parts

    assert fields["name"] == SKILL_NAME


def test_the_description_says_both_what_and_when(parts):
    """It is all an agent sees at discovery, so it must carry the trigger."""
    fields, _ = parts
    description = fields["description"]

    assert "Use when" in description, "must state when to reach for this"
    assert len(description) > 200, "too terse to match against a real task"
    assert len(description) <= 1024, "spec maximum; loaded for every skill"


def test_the_skill_defers_to_the_guide_rather_than_restating_it(parts):
    """Two copies of the manual would drift; the CLI stays authoritative."""
    _, body = parts

    assert "gtrends guide" in body
    # The spec caps SKILL.md at 500 lines; this one aims far lower, because
    # the manual it would otherwise restate already lives in `gtrends guide`.
    assert len(body.splitlines()) < 120, (
        "the skill is a router, not a second manual -- put detail in "
        "`gtrends guide`, which is tested by tests/test_help.py"
    )


def test_the_skill_names_the_traps_that_produce_wrong_answers(parts):
    _, body = parts

    for trap in ("zero", "entity", "provisional", "normalis"):
        assert trap in body.lower(), f"unmentioned failure mode: {trap}"


def test_the_repo_has_agent_instructions_distinct_from_the_skill():
    """AGENTS.md is for developing the tool; SKILL.md is for using it."""
    agents = (REPO / "AGENTS.md").read_text()

    assert "uv run pytest" in agents
    assert "tests/live" in agents


def test_the_root_skill_is_mapped_into_the_package_at_build_time():
    """Authored at the root, shipped inside the package, one copy of each."""
    config = tomllib.loads((REPO / "pyproject.toml").read_text())
    wheel = config["tool"]["hatch"]["build"]["targets"]["wheel"]

    assert wheel["packages"] == ["src/gtrendscli"]
    assert wheel["force-include"] == {
        "SKILL.md": "gtrendscli/skills/gtrends/SKILL.md"
    }
    assert SKILL.parent == REPO, "authored at the repository root"


# --- installation ------------------------------------------------------------


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A throwaway home directory, so tests never touch the real one."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    return tmp_path


def run(args):
    return CliRunner().invoke(main, args, obj=object())


def installed(target: Path) -> bool:
    return (target / "SKILL.md").is_file()


def test_the_skill_is_locatable_from_a_source_checkout_too():
    """The wheel path and the repository path must both resolve."""
    assert packaged_skill().is_file()
    assert packaged_skill().name == "SKILL.md"


def test_install_defaults_to_the_cross_tool_location(home):
    result = run(["skill", "install"])

    assert result.exit_code == 0
    assert installed(home / ".agents" / "skills" / "gtrends")


def test_the_installed_directory_is_named_for_the_skill(home):
    """The spec requires the parent directory to match the `name` field."""
    run(["skill", "install"])

    target = home / ".agents" / "skills" / "gtrends"
    assert target.name == "gtrends"
    assert "name: gtrends" in (target / "SKILL.md").read_text()


def test_install_reports_tool_directories_it_found(home):
    """Installing silently into four home directories would be presumptuous."""
    (home / ".claude").mkdir()
    (home / ".cursor").mkdir()

    result = run(["skill", "install"])

    assert "Claude Code" in result.output and "Cursor" in result.output
    assert "--all" in result.output
    assert not installed(home / ".claude" / "skills" / "gtrends")


def test_install_all_covers_every_detected_tool(home):
    (home / ".claude").mkdir()
    (home / ".gemini").mkdir()

    result = run(["skill", "install", "--all"])

    assert result.exit_code == 0
    assert installed(home / ".agents" / "skills" / "gtrends")
    assert installed(home / ".claude" / "skills" / "gtrends")
    assert installed(home / ".gemini" / "skills" / "gtrends")
    assert installed(home / ".gemini" / "config" / "skills" / "gtrends")


def test_absent_tools_are_not_invented(home):
    run(["skill", "install", "--all"])

    assert not (home / ".claude").exists()


def test_install_to_an_explicit_directory(home):
    target = home / "somewhere" / "skills"

    result = run(["skill", "install", "--to", str(target)])

    assert result.exit_code == 0
    assert installed(target / "gtrends")


def test_a_repository_scoped_install_is_just_a_relative_destination(
    home, monkeypatch
):
    """No --project flag: `--to .agents/skills` already says exactly that."""
    workspace = home / "repo"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    result = run(["skill", "install", "--to", ".agents/skills"])

    assert result.exit_code == 0
    assert installed(workspace / ".agents" / "skills" / "gtrends")


def test_an_existing_install_is_not_clobbered(home):
    run(["skill", "install"])
    marker = home / ".agents" / "skills" / "gtrends" / "MINE.md"
    marker.write_text("local edit")

    result = run(["skill", "install"])

    assert result.exit_code == 1
    assert "--force" in result.output
    assert marker.exists(), "a local edit must survive a refused install"


def test_force_replaces_an_existing_install(home):
    run(["skill", "install"])
    stale = home / ".agents" / "skills" / "gtrends" / "STALE.md"
    stale.write_text("old")

    result = run(["skill", "install", "--force"])

    assert result.exit_code == 0
    assert not stale.exists()
    assert installed(home / ".agents" / "skills" / "gtrends")


def test_link_tracks_the_package_instead_of_copying(home):
    """The directory is real, as the spec needs; only SKILL.md is linked."""
    result = run(["skill", "install", "--link"])

    target = home / ".agents" / "skills" / "gtrends"
    assert result.exit_code == 0
    assert target.is_dir() and not target.is_symlink()
    assert (target / "SKILL.md").is_symlink()
    assert installed(target)


def test_dry_run_writes_nothing(home):
    result = run(["skill", "install", "--dry-run"])

    assert result.exit_code == 0
    assert "would install" in result.output
    assert not (home / ".agents").exists()


# --- uninstall ---------------------------------------------------------------


def test_uninstall_removes_what_install_created(home):
    run(["skill", "install"])
    target = home / ".agents" / "skills" / "gtrends"
    assert installed(target)

    result = run(["skill", "uninstall"])

    assert result.exit_code == 0
    assert not target.exists()


def test_uninstall_says_so_when_there_is_nothing_there(home):
    result = run(["skill", "uninstall"])

    assert result.exit_code == 0
    assert "nothing to remove" in result.output


def test_uninstall_all_sweeps_every_known_location(home):
    (home / ".claude").mkdir()
    (home / ".gemini").mkdir()
    run(["skill", "install", "--all"])

    result = run(["skill", "uninstall", "--all"])

    assert result.exit_code == 0
    for location in (".agents/skills", ".claude/skills", ".gemini/skills"):
        assert not (home / location / "gtrends").exists()


def test_uninstall_all_finds_leftovers_from_removed_tools(home):
    """A tool can be uninstalled and leave its skill behind."""
    stale = home / ".cursor" / "skills" / "gtrends"
    run(["skill", "install", "--to", str(stale.parent)])
    assert installed(stale)

    result = run(["skill", "uninstall", "--all"])

    assert result.exit_code == 0
    assert not stale.exists()


def test_uninstall_refuses_to_delete_something_that_is_not_ours(home):
    """--to pointing somewhere unexpected must not destroy the contents."""
    theirs = home / "someone-elses" / "gtrends"
    theirs.mkdir(parents=True)
    (theirs / "important.txt").write_text("do not delete")

    result = run(["skill", "uninstall", "--to", str(theirs.parent)])

    assert result.exit_code == 1
    assert "refusing to delete" in result.output
    assert (theirs / "important.txt").exists()


def test_uninstall_removes_a_symlinked_install_without_touching_the_package(
    home,
):
    run(["skill", "install", "--link"])
    target = home / ".agents" / "skills" / "gtrends"
    assert (target / "SKILL.md").is_symlink()

    result = run(["skill", "uninstall"])

    assert result.exit_code == 0
    assert not target.exists()
    assert packaged_skill().is_file(), "removing the link spares the source"


def test_uninstall_dry_run_removes_nothing(home):
    run(["skill", "install"])

    result = run(["skill", "uninstall", "--dry-run"])

    assert "would remove" in result.output
    assert installed(home / ".agents" / "skills" / "gtrends")


def test_a_failed_symlink_falls_back_to_copying(home, monkeypatch):
    """Windows needs elevated rights for symlinks; a copy beats a traceback."""

    def refuse(*_args, **_kwargs):
        raise OSError("symlinks not permitted")

    monkeypatch.setattr(Path, "symlink_to", refuse)

    result = run(["skill", "install", "--link"])

    assert result.exit_code == 0
    target = home / ".agents" / "skills" / "gtrends"
    assert installed(target)
    assert not (target / "SKILL.md").is_symlink()


def test_copying_is_the_default(home):
    """Links point into the installing environment, which may be a cache."""
    run(["skill", "install"])

    assert not (
        home / ".agents" / "skills" / "gtrends" / "SKILL.md"
    ).is_symlink()


def test_force_refuses_to_replace_something_that_is_not_ours(home):
    """`--force` licenses replacing this skill, not whatever sits at a
    mistyped --to. This deleted a directory tree before it was guarded."""
    theirs = home / "work" / "gtrends"
    theirs.mkdir(parents=True)
    (theirs / "thesis.txt").write_text("years of work")
    (theirs / "sub").mkdir()
    (theirs / "sub" / "more.txt").write_text("more work")

    result = run(["skill", "install", "--to", str(theirs.parent), "--force"])

    assert result.exit_code == 1
    assert "refusing to replace" in result.output
    assert (theirs / "thesis.txt").read_text() == "years of work"
    assert (theirs / "sub" / "more.txt").exists()


def test_force_still_replaces_a_real_previous_install(home):
    run(["skill", "install"])
    target = home / ".agents" / "skills" / "gtrends"
    (target / "stale.txt").write_text("from an older version")

    result = run(["skill", "install", "--force"])

    assert result.exit_code == 0
    assert installed(target)
    assert not (target / "stale.txt").exists()


def test_an_unwritable_destination_is_reported_not_raised(home, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "mkdir", refuse)

    result = run(["skill", "install", "--to", str(home / "nope")])

    assert result.exit_code == 1
    assert "could not install into" in result.output
    assert "Traceback" not in result.output


def test_a_directory_with_an_unreadable_manifest_is_not_treated_as_ours(home):
    """Undecodable bytes are not evidence this tool wrote the directory."""
    theirs = home / "odd" / "gtrends"
    theirs.mkdir(parents=True)
    (theirs / "SKILL.md").write_bytes(b"\xff\xfe not utf-8 \x00")

    result = run(["skill", "uninstall", "--to", str(theirs.parent)])

    assert result.exit_code == 1
    assert "refusing to delete" in result.output
    assert (theirs / "SKILL.md").exists()
