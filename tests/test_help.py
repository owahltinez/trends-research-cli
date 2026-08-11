"""Help output is the only documentation some callers will ever have.

An agent driving this CLI may have no README, no source and no network. These
tests are the contract that `--help` and `gtrends guide` stay sufficient on
their own.
"""

import click
import pytest
from click.testing import CliRunner

from trends_research_cli.cli import main

RUNNER = CliRunner()


def walk(command, path=()):
    """Yield every (path, command) pair in the tree, groups included."""
    yield path, command

    if isinstance(command, click.Group):
        for name, sub in command.commands.items():
            yield from walk(sub, (*path, name))


ALL_COMMANDS = dict(walk(main))
ALL_PATHS = list(ALL_COMMANDS)
LEAF_PATHS = [
    path
    for path, cmd in ALL_COMMANDS.items()
    if not isinstance(cmd, click.Group)
]


def label(path) -> str:
    return " ".join(path) or "root"


def help_for(path) -> str:
    result = RUNNER.invoke(main, [*path, "-h"], obj=object())
    assert result.exit_code == 0, f"`{' '.join(path)} -h` failed"
    return result.output


@pytest.mark.parametrize("path", ALL_PATHS, ids=label)
def test_every_command_documents_itself(path):
    command = ALL_COMMANDS[path]

    assert command.help, f"`gtrends {' '.join(path)}` has no help text"
    assert help_for(path)


@pytest.mark.parametrize("path", ALL_PATHS, ids=label)
def test_every_option_has_help_text(path):
    """A bare `--geo TEXT` tells a caller nothing about what is accepted."""
    command = ALL_COMMANDS[path]
    undocumented = [
        param.name
        for param in command.params
        if isinstance(param, click.Option)
        and not param.help
        and param.name not in {"help", "version"}
    ]

    assert not undocumented, (
        f"`gtrends {' '.join(path)}` has undocumented options: {undocumented}"
    )


@pytest.mark.parametrize("path", LEAF_PATHS, ids=label)
def test_every_runnable_command_shows_a_worked_example(path):
    """Agents copy examples; a bare flag list invites a malformed call."""
    if path == ("guide",):
        return  # the guide is itself the example

    assert "gtrends" in (ALL_COMMANDS[path].epilog or ""), (
        f"`gtrends {' '.join(path)}` has no example in its epilog"
    )


def test_help_needs_no_credentials():
    """Discovering the tool must not require being set up to use it."""
    result = RUNNER.invoke(main, ["-h"])

    assert result.exit_code == 0
    assert "Usage" in result.output


def test_root_help_states_the_unit_and_the_exit_codes():
    """Both are needed to use output correctly and to branch on failure."""
    output = help_for(())

    assert "10,000,000" in output
    assert "Exit codes" in output
    assert "gtrends guide" in output


@pytest.mark.parametrize(
    "topic",
    [
        "10,000,000",  # the unit
        "no whole period",  # the clamp rule
        "UTC",  # day binning
        "provisional",  # the data horizon
        "too few",  # zeros are ambiguous
        "EXIT CODES",  # branching
        "--plain",  # composition
        "tidy long format",  # machine schema
        "entity find",  # how to get IDs
    ],
)
def test_the_guide_covers_every_rule_needed_to_avoid_a_wrong_answer(topic):
    result = RUNNER.invoke(main, ["guide"])

    assert result.exit_code == 0
    assert topic in result.output


def test_the_guide_needs_no_network_or_credentials():
    result = RUNNER.invoke(main, ["guide"])

    assert result.exit_code == 0
    assert len(result.output.splitlines()) > 80


@pytest.mark.parametrize("path", ALL_PATHS, ids=label)
def test_no_help_text_leaks_a_literal_paragraph_marker(path):
    r"""Click's `\b` is an ASCII backspace, not two characters.

    A raw docstring turns the marker into visible text on the first screen a
    user ever sees, and rewraps the paragraph it was meant to protect. This
    file is a contract and it missed exactly that once.
    """
    assert "\\b" not in help_for(path)
