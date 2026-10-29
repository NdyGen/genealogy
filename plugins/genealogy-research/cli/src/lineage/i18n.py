"""Output in the project's language. Messages are written in English in the code and are their own key;
translations live in locales/<language>/*.json. A message without a translation stays English.
"""

from __future__ import annotations

import datetime as dt
import json
from functools import cache
from pathlib import Path

from lineage import settings

LOCALES = Path(__file__).with_name("locales")
MONTHS = {
    "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December"),
    "nl": ("januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september",
           "oktober", "november", "december"),
}  # fmt: skip


@cache
def catalog(language: str) -> dict[str, str]:
    merged: dict[str, str] = {}
    for path in sorted((LOCALES / language).glob("*.json")):
        merged.update(json.loads(path.read_text(encoding="utf-8")))
    return merged


def language() -> str:
    return settings.current().language


def t(text: str, /, **values: object) -> str:
    """text translated into the output language, with {name} filled in from values."""
    template = catalog(language()).get(text, text) if language() != "en" else text
    return template.format(**values) if values else template


def month(number: int) -> str:
    return MONTHS.get(language(), MONTHS["en"])[number - 1]


def date(d: dt.date) -> str:
    """A calendar date as people write it in the output language: 1-3-1776 or 1 March 1776."""
    if language() == "nl":
        return f"{d.day}-{d.month}-{d.year}"
    return f"{d.day} {month(d.month)} {d.year}"
