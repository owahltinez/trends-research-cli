"""`gtrends guide` — everything needed to use this tool correctly, offline.

An agent driving this CLI may have no access to the README, the source, or the
web. This command is the whole operating manual in one place: every rule that
would otherwise be learned by getting a wrong answer.
"""

from __future__ import annotations

import click

GUIDE = """\
gtrends — Google Trends Research / Health Trends API

WHAT THIS IS
  The allow-listed research API, not the public Trends site. No hourly data,
  no 0-100 index, and access is granted per Google Cloud project. If requests
  are rejected, run `gtrends doctor` -- it distinguishes "not allow-listed"
  from "bad key" from "Knowledge Graph API not enabled", which the API itself
  reports identically.

THE UNIT
  value = P(term | date AND geography) x 10,000,000

  Already a share of searches. Never rescale it and never divide it by a
  "control" term: that normalises an already-normalised number, and has
  produced published errors. Every output states the unit.

TERMS
  Prefer entity IDs (/m/... or /g/...) over free text. Free text matches
  strings, so a wrong spelling or transliteration returns all zeros --
  indistinguishable from a real absence of searches. Bare strings work but
  always warn. Find IDs with `gtrends entity find`, and confirm one still
  means what you think with `gtrends entity verify`.

  Up to 30 terms per request. A term may combine entities with '+', which the
  API returns as one merged series.

DATES
  One format everywhere: --from and --to take YYYY, YYYY-MM or YYYY-MM-DD.
  Partial values expand outward. Omitting --to means that whole period when
  --from was partial, or "up to today" when it was a full date.

  Coarse intervals return FIXED CALENDAR PERIODS; the dates you give only
  select which periods overlap. So one rule applies everywhere:

    A range containing no whole period is an ERROR (exit 1).
    A wider range is CLAMPED to the whole periods inside it, and the
    dropped partial periods are reported as warnings.

  Asking for --interval month over six days will never quietly return the
  whole month. Every row carries date_start and date_end, so the coverage of
  each value is visible in the data rather than inferred from the request.

TIME ZONE AND FRESHNESS
  Days are binned in UTC. There is no timezone parameter. --to defaults to
  today in UTC, not local time.

  The data horizon sits about two days behind the current UTC date, and the
  API is inconsistent there: it rejects a short request ending inside that
  window, but returns those same days as part of a longer range. Because the
  value is a share and not a count, an incomplete day looks like an ordinary
  number. Any range running up to the present warns. A spike in the last two
  days is not evidence until it settles.

ZEROS
  A zero means "no activity" OR "too few distinct queries to release". The API
  does not distinguish them. Every series reports pct_zero and the longest run
  of zeros; over 50% zero warns. Treat a zero as unmeasured, not as absence of
  interest. Splitting sub-nationally makes this worse: a term visible for a
  country can be zero in every one of its regions.

  Display never rounds a small non-zero value down to 0.0, so a printed zero
  is always a real one.

COMMANDS
  gtrends doctor                      is my setup working?
  gtrends entity find <name>          name -> entity IDs, from two indexes
  gtrends entity verify <id> --is X   assert an ID still means X (exit 3)
  gtrends entity coverage <id>        does the ID capture what people type?
  gtrends series <id...>              the numbers
  gtrends queries <id>                strings people typed alongside
  gtrends topics <id>                 entities that co-occur (returns IDs)
  gtrends check censoring|variance|vs-public

  `series` groups with --by:
    date   (default)  one series per term over time
    region            one value per sub-region, regions as rows
    year   --years    the same calendar dates across years, years as columns

  --interval day|week|month|year sets the calendar period. --summary
  mean|median|sum|max|min collapses a series to one value over the exact dates
  requested; it is computed from daily values and refuses a coarse --interval,
  because the API can only aggregate whole calendar periods.

  `queries` and `topics` are month-granular -- a hard API limit, so a result
  is never evidence about a specific week. `series --by region` has no such
  limit and accepts any range down to a single day.

OUTPUT
  Human table by default. `series` takes the full set -- --json, --csv,
  --parquet PATH, --plain, --strict, --receipt, --raw-dir. The other commands
  take --json, and `queries`/`topics`/`entity find` also take --plain. Check
  `<command> -h` rather than assuming.

  Machine formats are always tidy long format, one row per
  date_start x term x group, and never pivot. The human table pivots only when
  exactly one axis varies; when two do it stays long and says so.

  Warnings appear in every format, including --json and --plain, where they
  go to stderr so stdout stays pipeable. Detect a clamped window, a censored
  series or provisional data from the output rather than from prose. --strict
  turns any warning into exit 4.

  Notes are separate from warnings: they are caveats that hold whatever the
  data says, such as a hard API limit or a naming scheme. --strict ignores
  them, or it would fail on flawless data.

PROVENANCE
  --raw-dir DIR archives every raw response. --receipt FILE records every call
  made, with timestamps and warnings, and never the API key. The API is
  sampled: an identical query need not return identical numbers tomorrow, and
  `gtrends check variance` measures that directly.

  Note that the Google APIs Terms of Service, section 5.e, restrict creating
  permanent copies of content returned from the APIs "unless expressly
  permitted by the content owner". --raw-dir does exactly that, which is what
  makes a published number checkable. Confirm your access grant covers it
  before relying on the archive. --receipt does not store response content,
  only the calls made, so it is unaffected.

ATTRIBUTION
  Reusing Trends data requires crediting Google. Every output carries
  "Data source: Google Trends (https://www.google.com/trends)" in its
  metadata; cite it alongside any figure you publish.

COMPOSITION
  --plain makes commands pipe into each other:

    gtrends series $(gtrends topics /m/0cycc --geo US --from 2025-07 \\
        --top 5 --plain) --geo US --from 2025-07

EXIT CODES
  0  success
  1  usage error: bad flags, unparseable dates, no whole period in range
  2  API or network error after retries
  3  assertion failure, e.g. `entity verify` name mismatch
  4  warnings were raised and --strict was given

WHAT THIS TOOL WILL NOT DO
  No p-values, significance tests or verdicts -- it returns well-labelled
  numbers with their caveats and you run your own test. No hourly data, since
  the API has none. No forecasting, modelling or plotting.

A TYPICAL SEQUENCE
  gtrends doctor
  gtrends entity find "influenza" --geo US
  gtrends entity verify /m/0cycc --is "Influenza"
  gtrends series /m/0cycc --geo US --from 2025-01 --to 2025-12 --json
  gtrends check censoring /m/0cycc --geo US --from 2025-01 --to 2025-12
"""


@click.command()
def guide() -> None:
    """Print the full operating manual: units, dates, caveats, exit codes.

    Written for callers with no other documentation to hand.
    """
    click.echo(GUIDE, nl=False)
