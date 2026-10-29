"""GEDCOM dates reduced to year ranges, which is the precision plausibility checks need."""

from __future__ import annotations

import re
from dataclasses import dataclass

# ABT/EST/CAL dates in old records are often off by several years; a narrower margin
# produces false alarms in the checks.
APPROX_MARGIN = 5

_YEAR = re.compile(r"(?<!\d)(\d{3,4})(?:/\d{1,2})?(?!\d)")
_RANGE = re.compile(r"^(?:BET|FROM)\s+(.+?)\s+(?:AND|TO)\s+(.+)$")
_CALENDAR_ESCAPE = re.compile(r"@#D[^@]*@\s*")


@dataclass(frozen=True)
class GedDate:
    raw: str
    year: int | None
    earliest: int | None
    latest: int | None

    def __str__(self) -> str:
        return self.raw


def _find_year(text: str) -> int | None:
    match = _YEAR.search(text)
    return int(match[1]) if match else None


def parse_date(raw: str) -> GedDate:
    text = _CALENDAR_ESCAPE.sub("", raw.upper()).strip()

    if text.startswith("(") or text.startswith("INT "):
        year = _find_year(text.removeprefix("INT ").split("(")[0])
        return GedDate(raw, year, year, year)

    if match := _RANGE.match(text):
        low, high = _find_year(match[1]), _find_year(match[2])
        return GedDate(raw, low, low, high)

    keyword, _, rest = text.partition(" ")
    if keyword in ("BEF", "TO"):
        year = _find_year(rest)
        return GedDate(raw, year, None, year)
    if keyword in ("AFT", "FROM"):
        year = _find_year(rest)
        return GedDate(raw, year, year, None)
    if keyword in ("ABT", "EST", "CAL"):
        year = _find_year(rest)
        if year is None:
            return GedDate(raw, None, None, None)
        return GedDate(raw, year, year - APPROX_MARGIN, year + APPROX_MARGIN)

    year = _find_year(text)
    return GedDate(raw, year, year, year)


def years_between(start: GedDate, end: GedDate) -> tuple[int | None, int | None]:
    """Smallest and largest possible number of years from start to end."""
    low = (
        end.earliest - start.latest
        if end.earliest is not None and start.latest is not None
        else None
    )
    high = (
        end.latest - start.earliest
        if end.latest is not None and start.earliest is not None
        else None
    )
    return low, high
