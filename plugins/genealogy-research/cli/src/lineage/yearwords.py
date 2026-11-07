"""Years written in words, in early modern Dutch and in Latin: "1700 Zeeven entagtig", "seventien hondert
seven en tachtig", "millesimo septingentesimo octogesimo septimo". Helpers misread them (1777 for 1787)."""

from __future__ import annotations

import re

from lineage.checks import normalize

_DUTCH = {
    "een": 1, "eenen": 1, "twee": 2, "drie": 3, "vier": 4, "vyf": 5, "vijf": 5, "vijff": 5, "vyff": 5,
    "zes": 6, "ses": 6, "zeven": 7, "seven": 7, "zeeven": 7, "seeven": 7, "acht": 8, "agt": 8,
    "negen": 9, "neegen": 9, "tien": 10, "thien": 10, "elf": 11, "elff": 11, "twaalf": 12, "twaelf": 12,
    "dertien": 13, "veertien": 14, "vijftien": 15, "vyftien": 15, "zestien": 16, "sestien": 16,
    "zeventien": 17, "seventien": 17, "zeeventien": 17, "achttien": 18, "agttien": 18, "agtien": 18,
    "negentien": 19, "neegentien": 19,
    "twintig": 20, "twintich": 20, "dertig": 30, "dertich": 30, "veertig": 40, "veertich": 40,
    "vijftig": 50, "vyftig": 50, "vijftich": 50, "zestig": 60, "sestig": 60, "sestich": 60,
    "zeventig": 70, "seventig": 70, "zeeventig": 70, "seventich": 70,
    "tachtig": 80, "tagtig": 80, "tachtich": 80, "tachentich": 80, "tagentig": 80,
    "negentig": 90, "neegentig": 90, "negentich": 90,
}  # fmt: skip
_LATIN = {
    "primo": 1, "secundo": 2, "tertio": 3, "quarto": 4, "quinto": 5, "sexto": 6, "septimo": 7, "octavo": 8,
    "nono": 9, "decimo": 10, "undecimo": 11, "duodecimo": 12,
    "vigesimo": 20, "vicesimo": 20, "trigesimo": 30, "tricesimo": 30, "quadragesimo": 40, "quinquagesimo": 50,
    "sexagesimo": 60, "septuagesimo": 70, "octogesimo": 80, "nonagesimo": 90,
    "centesimo": 100, "ducentesimo": 200, "trecentesimo": 300, "quadringentesimo": 400, "quingentesimo": 500,
    "sexcentesimo": 600, "septingentesimo": 700, "octingentesimo": 800, "nongentesimo": 900, "millesimo": 1000,
}  # fmt: skip
_HUNDRED = ("honderd", "hondert", "hondt")
_THOUSAND = ("duizend", "duysent", "duijsent", "duysend", "duizent")
_WORDS = sorted([*_DUTCH, *_HUNDRED, *_THOUSAND, "en"], key=len, reverse=True)
_DUTCH_TOKEN = re.compile(r"\d+|" + "|".join(_WORDS))
_LATIN_TOKEN = re.compile(r"\d+|(" + "|".join(sorted((w[:-1] for w in _LATIN), key=len, reverse=True)) + r")[oiaue]s?\b")


def parse(text: str) -> int | None:
    """The year the words give, or None when they hold no number word. Other words ("anno", "den") are
    skipped."""
    flat = normalize(text)
    return _latin(flat) or _dutch(flat)


def _tokens(word: str) -> list[str] | None:
    found, position = [], 0
    while position < len(word):
        if not (m := _DUTCH_TOKEN.match(word, position)):
            return None
        found.append(m[0])
        position = m.end()
    return found


def _dutch(flat: str) -> int | None:
    total = current = words = 0
    for word in re.findall(r"[a-z0-9]+", flat):
        for token in _tokens(word) or []:
            if token.isdigit():
                current += int(token)
            elif token in _HUNDRED:
                current = (current or 1) * 100
                words += 1
            elif token in _THOUSAND:
                total += (current or 1) * 1000
                current = 0
                words += 1
            elif token != "en":
                current += _DUTCH[token]
                words += 1
    return total + current if words else None


def _latin(flat: str) -> int | None:
    total = words = 0
    for m in _LATIN_TOKEN.finditer(flat):
        if m[0].isdigit():
            total += int(m[0])
        else:
            total += next(v for k, v in _LATIN.items() if k[:-1] == m[1])
            words += 1
    return total if words else None
