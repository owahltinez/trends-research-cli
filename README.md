# gtrendscli

A CLI for the **Google Trends Research / Health Trends API**, aimed at
journalism and OSINT work.

This wraps the allow-listed research API, **not** the public Trends site. It
returns absolute probabilities rather than the familiar 0–100 index, it has no
hourly data, and access must be granted per project. Run `gtrends doctor` first
— it tells you which of those is stopping you.

The API's real behaviour is largely undocumented, and most of it is a trap.
What this tool knows about it is recorded in the module docstrings and asserted
against the live API by `tests/live/` — so if the API changes underneath you,
those tests fail rather than the numbers quietly going wrong.

## Install

```sh
uv sync
cp .env.example .env   # then fill in TRENDS_API_KEY
gtrends doctor
```

## The unit

```
value = P(term | date AND geography) x 10,000,000
```

Already a share. Never rescaled, never normalised against a "control" — doing
so divides a probability by a probability and has produced published errors.
Every output states the unit, geo, interval, endpoint and retrieval time.

## Time zone and freshness

**Days are binned in UTC.** Google documents this for daily Trends data, and
this API exposes no timezone parameter to override it. Corroborated directly:
the API serves the current UTC date while it is still yesterday in US Pacific
time. `--to` therefore defaults to today *in UTC*, not local time — on a Pacific
machine, local time would silently drop the newest day.

**The data horizon sits about two days back**, and the API is inconsistent
about it. A short request ending inside that window is rejected outright with a
`400`, but a long request spanning the same days returns them anyway. Because
the metric is a **share** rather than a count, those trailing days come back
looking like perfectly ordinary values — nothing in the number reveals it
covers three hours rather than twenty-four. Any range running up to the present
therefore warns, and a late spike is not evidence until it settles.

## Dates

One format everywhere: `--from` and `--to` take `YYYY`, `YYYY-MM` or
`YYYY-MM-DD`. Partial values expand outward.

```sh
--from 2026-07                     # all of July
--from 2021 --to 2026              # six whole years
--from 2026-07-21 --to 2026-07-26  # exactly those six days
--from 2026-07-21                  # the 21st to today
```

Coarse intervals return **fixed calendar periods**, and the requested dates only
select which ones overlap. So there is one rule: if a range contains no whole
period, it errors; otherwise it clamps to the whole periods inside and reports
what was dropped. Asking for `--interval month` over six days will never
silently hand back the whole month.

## Documentation

### For AI agents

`SKILL.md` at the repository root is a portable [Agent
Skill](https://agentskills.io) — the open format read by Claude Code, Codex,
Cursor, Gemini CLI, Copilot and others. It ships with the package, but
installing the CLI does not put it where agents look, so:

```sh
uv tool install gtrendscli
gtrends skill install          # ~/.agents/skills, the cross-tool location
gtrends skill install --all    # plus every agent tool found on this machine
gtrends skill install --to .agents/skills   # this repository only
gtrends skill uninstall --all  # remove it again
```

`install` reports any tool-specific directories it finds rather than writing
into several home directories uninvited, and `uninstall` only ever removes a
directory that actually holds this skill.

It **copies** rather than symlinking. A link would track package upgrades, but
it points into whichever environment the CLI was installed into — under `uvx`
that is a prunable cache, so the skill would work today and vanish after
`uv cache prune`. Re-run `gtrends skill install --force` after an upgrade;
staleness is cheap here because the skill routes to `gtrends guide`, which
ships in the binary and cannot go stale. `--link` is available for a durable
install into a private skills directory; do not commit one to a repository,
where an absolute symlink into your own home is broken for everyone else.

The skill routes to `gtrends guide` rather than restating it. `AGENTS.md`
covers developing this repo, which is a different job.

`gtrends guide` prints the complete operating manual — units, date rules, the
zero caveat, exit codes — with no network or credentials needed. Every command
and subcommand also carries `-h/--help` with a worked example.

```sh
gtrends guide          # everything, in one place
gtrends series -h      # flags and an example for one command
```

## Commands

```sh
gtrends guide                    # the full manual, offline
gtrends doctor                   # is my setup working?
gtrends entity find|verify|coverage
gtrends series <id...>           # the numbers
gtrends queries <id>             # what strings people typed alongside
gtrends topics <id>              # what entities co-occur (returns IDs)
gtrends check censoring|variance|vs-public
```

### series

```sh
gtrends series /m/0cycc --geo US --from 2025-07-01 --to 2025-07-07
gtrends series /m/0cycc /m/07__7 --geo US --from 2025-07     # terms as columns
gtrends series /m/0cycc --geo US --from 2025-07 --by region  # regions as rows
gtrends series /m/0cycc --geo US --from 07-21 --to 07-23 \
    --by year --years 2023-2025                              # years as columns
gtrends series /m/0cycc --geo US --from 2025-07-21 --to 2025-07-26 --summary mean
```

`--interval` takes `day`, `week`, `month` or `year`. `--by region` accepts any
range down to a single day; `queries` and `topics` are month-only. Long ranges
chunk past the ~380-point ceiling automatically and concatenate with no
bridging factor, because the values are absolute.

`--geo` takes a country (`US`), a sub-national region (`US-NY`) or a bare
Nielsen DMA number (`501` for the New York media market). Up to 30 terms per
request; requests are throttled to the documented 2 per second.

### entity

Getting IDs right matters more than any analysis decision. `find` consults both
the Knowledge Graph *and* the Trends topic index, because neither is complete —
`/m/0cycc` is what Trends returns for influenza and serves data for, yet
`kgsearch` has never heard of it.

```sh
gtrends entity find "influenza" --geo US
gtrends entity verify /m/07__7 --is "Vaccine"
gtrends entity coverage /m/0cycc --text flu --text grippe \
    --geo US --from 2025-07
```

`coverage` answers "does this entity capture the words people actually type?" by
fetching the entity and each variant over the same window and comparing the
entity against the summed variants.

### Composition

`--plain` gives bare values, one per line, so commands pipe into each other:

```sh
gtrends series $(gtrends topics /m/0cycc --geo US --from 2025-07 --top 5 --plain) \
    --geo US --from 2025-07
```

## Output

Human table by default. `series` takes the full set — `--json`, `--csv`,
`--parquet PATH`, `--plain`, `--strict`, `--receipt`. Other commands take
`--json`, and `queries`/`topics`/`entity find` also take `--plain`; check
`<command> -h`. Machine formats are **always tidy long format**
— one row per `date_start × term × group` — and never pivot; the table pivots
only when exactly one axis varies.

Warnings travel with the data in every format — including `--plain`, where
they go to stderr so stdout stays pipeable — so an agent detects a clamped
window or a censored series from the output rather than from prose. *Notes*
are separate: caveats that hold whatever the data says, which `--strict`
deliberately ignores.

```sh
gtrends series ... --raw-dir raw/     # archive every response
gtrends series ... --receipt run.json # how each number was obtained
gtrends series ... --strict           # exit 4 if anything warned
```

Every output carries `Data source: Google Trends (https://www.google.com/trends)`
in its metadata — reusing Trends data requires crediting Google, so cite it
with any figure you publish.

One caveat on `--raw-dir`: the [Google APIs Terms of
Service](https://developers.google.com/terms) §5.e restrict creating permanent
copies of API content "unless expressly permitted by the content owner", and an
archive is exactly that. Check your access grant covers it. `--receipt` records
only the calls made, not response content, so it is unaffected.

## Zeros

A zero means *no activity* **or** *too few distinct queries to release*. The API
does not distinguish them. Every series reports `pct_zero` and the longest zero
run, anything over 50% zero warns, and display formatting will never round a
small non-zero value down to `0.0`.

## Exit codes

| 0 | success |
| 1 | usage error: bad flags, unparseable dates, clamp violation |
| 2 | API or network error after retries |
| 3 | assertion failure, e.g. `entity verify` mismatch |
| 4 | warnings raised under `--strict` |

## What it does not do

No p-values, no significance tests, no verdicts — the tool returns
well-labelled numbers with their coverage caveats and you run your own test.
No hourly data (the API has none). No forecasting, modelling or plotting.

## Test

```sh
uv run pytest              # offline; fast, no network
uv run pytest -m live      # also hits the real API; needs TRENDS_API_KEY
readability check src tests --fix
```

The live suite is the project's documentation of the API itself: it asserts
every undocumented behaviour this tool relies on — the parameter families, the
calendar-period bleeding, the point ceiling, the UTC binning and data horizon —
against the real service.
