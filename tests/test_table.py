"""The human table and its pivot rule.

Machine formats are always tidy long format. The table pivots only when exactly
one axis varies, so a reader never has to guess what a column means.
"""

from datetime import date

from gtrendscli.output.result import one_line
from gtrendscli.output.table import format_value, to_table
from gtrendscli.record import By, Record


def daily(day: int, term: str, value: float, group: str = "") -> Record:
    return Record(
        date_start=date(2026, 7, day),
        date_end=date(2026, 7, day),
        term=term,
        group=group,
        value=value,
    )


def test_single_term_daily_collapses_the_two_date_columns():
    table = to_table([daily(1, "flu", 10.0), daily(2, "flu", 20.0)], by=By.DATE)

    assert table.columns == ["date", "flu"]
    assert table.rows == [["2026-07-01", "10.0"], ["2026-07-02", "20.0"]]
    assert table.pivoted


def test_coarse_periods_keep_both_date_columns():
    """When a row spans a period, its true coverage must be visible."""
    records = [
        Record(date(2026, 7, 1), date(2026, 7, 31), "flu", "", 10.0),
        Record(date(2026, 8, 1), date(2026, 8, 31), "flu", "", 20.0),
    ]

    table = to_table(records, by=By.DATE)

    assert table.columns == ["date_start", "date_end", "flu"]
    assert table.rows[0] == ["2026-07-01", "2026-07-31", "10.0"]


def test_several_terms_become_columns():
    records = [
        daily(1, "flu", 10.0),
        daily(1, "vaccine", 30.0),
        daily(2, "flu", 20.0),
        daily(2, "vaccine", 40.0),
    ]

    table = to_table(records, by=By.DATE)

    assert table.columns == ["date", "flu", "vaccine"]
    assert table.rows == [
        ["2026-07-01", "10.0", "30.0"],
        ["2026-07-02", "20.0", "40.0"],
    ]


def test_groups_become_columns_when_there_is_one_term():
    records = [
        Record(date(2021, 7, 21), date(2021, 7, 21), "flu", "2021", 10.0),
        Record(date(2026, 7, 21), date(2026, 7, 21), "flu", "2026", 30.0),
    ]

    table = to_table(records, by=By.YEAR)

    assert table.columns == ["date", "2021", "2026"]
    assert table.rows == [["07-21", "10.0", "30.0"]]


def test_years_become_columns_keyed_on_the_calendar_day():
    """Acceptance test 9: one column per year, no test statistic."""
    records = [
        Record(date(2021, 7, 21), date(2021, 7, 21), "flu", "2021", 10.0),
        Record(date(2026, 7, 21), date(2026, 7, 21), "flu", "2026", 50.0),
        Record(date(2021, 7, 22), date(2021, 7, 22), "flu", "2021", 11.0),
        Record(date(2026, 7, 22), date(2026, 7, 22), "flu", "2026", 51.0),
    ]

    table = to_table(records, by=By.YEAR)

    assert table.columns == ["date", "2021", "2026"]
    assert table.rows == [["07-21", "10.0", "50.0"], ["07-22", "11.0", "51.0"]]


def test_two_varying_axes_fall_back_to_long_format():
    """Pivoting here would need a column to mean two things at once.

    Regions are exempt: they get their own grid, terms across and regions down,
    which stays unambiguous however many of each there are.
    """
    records = [
        Record(date(2021, 7, 21), date(2021, 7, 21), "flu", "2021", 10.0),
        Record(date(2021, 7, 21), date(2021, 7, 21), "vaccine", "2026", 20.0),
    ]

    table = to_table(records, by=By.YEAR)

    assert not table.pivoted
    assert table.columns == ["date_start", "date_end", "term", "group", "value"]
    assert table.rows[0] == ["2021-07-21", "2021-07-21", "flu", "2021", "10.0"]


def test_missing_combinations_render_as_blank_not_zero():
    """A zero means suppressed-or-absent, so it must never stand in for
    'not fetched'."""
    records = [daily(1, "flu", 10.0), daily(2, "vaccine", 20.0)]

    table = to_table(records, by=By.DATE)

    assert table.rows == [
        ["2026-07-01", "10.0", ""],
        ["2026-07-02", "", "20.0"],
    ]


def test_small_values_never_render_as_a_zero():
    """Zeros carry meaning here, so rounding must not manufacture one."""
    assert format_value(0.0) == "0"
    assert format_value(0.04) != "0.0"
    assert float(format_value(0.04)) > 0
    assert format_value(123.4567890123456) == "123.5"


def test_regions_are_rows_not_columns():
    """A breakdown covers one period, so regions in columns would be one row
    hundreds of columns wide."""
    records = [
        daily(1, "flu", 50.0, group="US-CA"),
        daily(1, "flu", 90.0, group="US-NY"),
        daily(1, "flu", 70.0, group="US-TX"),
    ]

    table = to_table(records, by=By.REGION)

    assert table.columns == ["region", "flu"]
    assert [row[0] for row in table.rows] == ["US-NY", "US-TX", "US-CA"]


def test_region_rows_carry_every_term_as_a_column():
    records = [
        daily(1, "flu", 50.0, group="US-CA"),
        daily(1, "vaccine", 20.0, group="US-CA"),
    ]

    table = to_table(records, by=By.REGION)

    assert table.columns == ["region", "flu", "vaccine"]
    assert table.rows == [["US-CA", "50.0", "20.0"]]


def test_a_newline_in_a_comment_value_is_escaped_not_emitted():
    """Second line of defence, for values that do not come from a flag: a
    reader stripping `#` lines would take a forged line as data."""
    forged = one_line("US\n1999-01-01,1999-01-01,forged,,99999")

    assert "\n" not in forged
    assert "\\x0a" in forged, "escaped, so the oddity stays visible"
    assert "forged" in forged, "and nothing is silently dropped"
