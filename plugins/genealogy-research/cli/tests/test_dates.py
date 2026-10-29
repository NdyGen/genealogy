import pytest

from lineage.dates import APPROX_MARGIN, parse_date, years_between


@pytest.mark.parametrize(
    ("raw", "year", "earliest", "latest"),
    [
        ("12 MAR 1850", 1850, 1850, 1850),
        ("1850", 1850, 1850, 1850),
        ("ABT 1850", 1850, 1850 - APPROX_MARGIN, 1850 + APPROX_MARGIN),
        ("BEF 1900", 1900, None, 1900),
        ("AFT 1900", 1900, 1900, None),
        ("BET 1850 AND 1855", 1850, 1850, 1855),
        ("FROM 1 JAN 1850 TO 1860", 1850, 1850, 1860),
        ("TO 1860", 1860, None, 1860),
        ("3 JAN 1700/01", 1700, 1700, 1700),
        ("@#DJULIAN@ 12 MAR 1650", 1650, 1650, 1650),
        ("INT 1850 (per baptism register)", 1850, 1850, 1850),
    ],
)
def test_parse_date(raw, year, earliest, latest):
    date = parse_date(raw)
    assert (date.year, date.earliest, date.latest) == (year, earliest, latest)
    assert str(date) == raw


@pytest.mark.parametrize("raw", ["SERVANT", "nn", "(unknown)", "ABT"])
def test_unreadable_date_has_no_year(raw):
    assert parse_date(raw).year is None


def test_years_between_uses_full_range():
    assert years_between(parse_date("ABT 1850"), parse_date("1900")) == (45, 55)
    assert years_between(parse_date("BEF 1850"), parse_date("1900")) == (50, None)
