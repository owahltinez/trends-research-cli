# AGENTS.md

Instructions for agents **working on this repository**. To *use* the tool
rather than develop it, see `SKILL.md` or run `gtrends guide`.

## Setup

```sh
uv sync                     # add --extra parquet for Parquet output
cp .env.example .env        # then fill in TRENDS_API_KEY
```

## Checks — all three must pass before you call anything done

```sh
uv run pytest                       # offline; fast, no network
uv run pytest -m live               # hits the real API; needs TRENDS_API_KEY
readability check src tests --fix
```

## How this project treats the API

The Trends API is almost entirely undocumented and most of its behaviour is a
trap. Two rules follow, and they are the point of the whole design:

**Never encode a belief about the API without asserting it in `tests/live/`.**
That suite is the project's documentation of the service. Every claim in a
module docstring — parameter families, date formats, the point ceiling, UTC
binning, the data horizon — has a live test behind it. Reconstructing behaviour
from memory has been wrong every single time it was tried here; probe it.

**Prefer a table to a rule.** Four properties vary independently across
endpoints and nothing about an endpoint's name predicts them: `regions` uses
restriction-style parameter names yet accepts full dates, `graph` picks its own
resolution, month-granular endpoints report caller errors as `500`. Clever
generalisations break. See `api/endpoints.py`.

## Design invariants

- **Never rescale a value.** It is already `P(term | date, geo) x 1e7`.
  Dividing by a "control" normalises twice and has produced published errors.
- **A zero is ambiguous** — no activity *or* suppressed. Never let display or
  arithmetic manufacture one; `format_value` deliberately avoids rounding a
  small value to `0.0`.
- **Refuse rather than silently widen.** A range with no whole calendar period
  is an error. Returning the containing month is the worst available failure.
- **Machine formats are tidy long format and never pivot.** Only the human
  table pivots, and only when exactly one axis varies.
- **The API key lives in the transport and nowhere else**, so parameters stay
  safe to log, archive and put in a run receipt.

## Testing

Test-driven: write the failing test first, watch it fail for the right reason,
then implement. Everything above `api/client.py` is exercised offline against a
fake `Transport`; no unit test performs I/O. Live tests are marked
`@pytest.mark.live` and skipped by default.

`tests/test_help.py` is a contract, not a formality: help output is the only
documentation some callers ever see. It has already caught epilogs that
silently failed to apply.

## Documentation

`gtrends guide` is the single source of truth for how to use the tool. The
README and `SKILL.md` point at it rather than restating it —
duplicating that content creates a second source that will drift. If you add a
rule a caller must know, put it in the guide and add a `tests/test_help.py`
assertion that it is covered.

## The packaged Agent Skill

`SKILL.md` follows the open [Agent Skills](https://agentskills.io)
spec. It is authored at the repository root, where it is visible, and
`force-include` in pyproject maps it to `gtrendscli/skills/gtrends/SKILL.md`
inside the wheel so `importlib.resources` can find it after install. One copy,
two locations that both have to resolve — `packaged_skill()` checks the wheel
path then the checkout.

The spec's rule that `name` must match its parent directory applies to the
*installed* skill, not the authored one: `gtrends skill install` always creates
a directory named for the skill. Those install locations are per-tool, with
`~/.agents/skills` the emerging cross-tool one. Validate changes with:

```sh
skills-ref validate .                     # the reference validator
uv run pytest tests/test_skill.py        # our own constraints
```

Keep it thin. It routes to `gtrends guide`; it does not restate it.

## Conventions

- Small functions; blocks of a few lines separated by blank lines, each with a
  comment saying why rather than what.
- Comments explain non-obvious decisions and compromises. The code should read
  from its comments alone.
- Do not add yourself as a commit co-author, and keep tool names out of commit
  messages.
- Ask before pushing.
