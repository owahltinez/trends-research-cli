---
name: gtrends
description: Measure Google search interest by term, place and date using the gtrends CLI — absolute probability series, sub-national and media-market breakdowns, related queries and topics, and entity-ID lookup. Use when a task involves Google Trends, search interest, query volume over time or by geography, or verifying a claim about what people were searching for. Not for the public trends.google.com 0-100 index or hourly data.
license: MIT
---

# gtrends

A CLI over the Google Trends Research / Health Trends API, aimed at journalism
and OSINT work. It returns **absolute probabilities**, not the familiar 0–100
index, and access is allow-listed per Google Cloud project.

## Read the manual first

```sh
gtrends guide
```

That prints the complete operating manual — units, date rules, caveats, output
schema, exit codes — offline, with no credentials needed. **Read it before
issuing your first query.** It is the single source of truth; this skill only
tells you when to reach for the tool and which mistakes cost a wrong answer.

Every command also has `-h` with a worked example.

## Workflow

```sh
gtrends doctor                                   # 1. can I use this at all?
gtrends entity find "<name>" --geo US            # 2. name -> entity ID
gtrends entity verify /m/xxxx --is "<name>"      # 3. does the ID mean that?
gtrends series /m/xxxx --geo US --from ... --json  # 4. the numbers
gtrends check censoring /m/xxxx --geo US --from ...  # 5. can I trust them?
```

Steps 1–3 are cheap and prevent the expensive failures. Skipping step 2 is the
single most common way to get a confidently wrong answer.

## The five ways this data misleads

1. **Free text is not an entity.** A bare string matches spellings, so a wrong
   transliteration returns all zeros — indistinguishable from a real absence.
   Use `/m/…` or `/g/…` IDs. The tool warns, but the warning is easy to skip.
2. **Zeros are ambiguous.** A zero means *no activity* **or** *too few queries
   to release*. Never report one as "nobody searched for this". Check
   `pct_zero`.
3. **The values are already a share.** Never divide one series by another to
   "normalise" it — that normalises twice. There is deliberately no flag for it.
4. **Coarse intervals return whole calendar periods**, not your date range. The
   tool refuses the dangerous cases and reports what it dropped; read the
   warnings rather than assuming your dates were honoured.
5. **The last two days are provisional.** Days are binned in UTC and the API's
   horizon lags. A partial day looks like a normal value because the metric is
   a share. A spike in the last 48 hours is not yet a story.

## For programmatic use

Pass `--json`. Output is tidy long format (`date_start`, `date_end`, `term`,
`group`, `value`) with `meta` and `warnings` alongside — **check `warnings`,
they are how the tool tells you the data cannot support your question**. Add
`--strict` to turn any warning into a non-zero exit.

Exit codes: `0` ok, `1` usage error, `2` API error, `3` assertion failed
(e.g. `entity verify` mismatch), `4` warnings under `--strict`.

## Reporting a number

Use `--raw-dir` to archive responses and `--receipt` to record every call made.
The API is sampled: an identical query need not return identical numbers
tomorrow, and `gtrends check variance` measures that directly. If asked why a
figure disagrees with trends.google.com, run `gtrends check vs-public` — the
shapes should agree, the values cannot, because the public index renormalises.

## This tool will not

Do statistics (no p-values or verdicts — it returns labelled numbers and you
run your own test), return hourly data (the API has none), or plot anything.
