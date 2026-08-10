"""Shared help strings.

Kept in one place so the same flag reads identically on every command, and so
an agent that only ever sees one subcommand's ``--help`` still learns the rules
that would otherwise cost it a failed request to discover.
"""

GEO = (
    "Country (US), sub-national region (US-NY), or a bare Nielsen DMA number "
    "(501 = New York media market). Required."
)

DATE_FROM = (
    "Start date: YYYY, YYYY-MM or YYYY-MM-DD. Partial values expand outward, "
    "so 2026-07 means all of July."
)

DATE_TO = (
    "End date, same formats. Omitted: a partial --from means exactly that "
    "period (--from 2026-07 is July alone), a full date means up to today UTC."
)

MONTH_ONLY = (
    "This endpoint is month-granular. A range containing no whole month is "
    "rejected; a wider one is clamped to whole months and the dropped partials "
    "are reported."
)

JSON = (
    "Machine-readable output. Warnings are included, so they stay detectable."
)

PLAIN = "Bare values, one per line, for shell composition."
