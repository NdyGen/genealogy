"""Building a tree from scratch: an empty GEDCOM, and persons, families and children added one at a time.

Used when someone starts without an export from another program. Every fact gets a source, even if it is
only "told by my aunt": that is where research picks up later. Records are appended with lineage.edit, so a
tree that came from elsewhere keeps its own lines.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from lineage import edit
from lineage.dates import parse_date
from lineage.i18n import t

MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
MONTH_NAMES = {
    **{m.lower(): i for i, m in enumerate(MONTHS, 1)},
    **{
        name: i
        for i, names in enumerate(
            (
                ("january", "januari", "jan."),
                ("february", "februari", "feb.", "febr."),
                ("march", "maart", "mrt", "mrt."),
                ("april", "apr."),
                ("mei",),
                ("june", "juni"),
                ("july", "juli"),
                ("august", "augustus", "aug."),
                ("september", "sept", "sep."),
                ("october", "oktober", "okt", "okt."),
                ("november", "nov."),
                ("december", "dec."),
            ),
            1,
        )
        for name in names
    },
}
QUALIFIERS = {
    "ABT": ("abt", "about", "ca", "ca.", "circa", "c.", "omstreeks", "rond", "ongeveer", "±"),
    "BEF": ("bef", "before", "voor", "vóór"),
    "AFT": ("aft", "after", "na"),
    "EST": ("est", "estimated", "geschat"),
}
EVENTS = {"birth": "BIRT", "baptism": "CHR", "death": "DEAT", "burial": "BURI"}
HEADER = ["0 HEAD", "1 SOUR LINEAGE", "1 GEDC", "2 VERS 5.5.1", "2 FORM LINEAGE-LINKED", "1 CHAR UTF-8"]


class BuildError(ValueError):
    pass


@dataclass(frozen=True)
class Event:
    tag: str
    date: str = ""
    place: str = ""


def new_tree(path: Path) -> None:
    if path.exists():
        raise BuildError(t("{path} already exists", path=path))
    path.parent.mkdir(parents=True, exist_ok=True)
    edit.write(path, [*HEADER, "0 TRLR", ""])


def _day_month_year(day: str, month: int, year: str) -> str:
    if not 1 <= month <= 12:
        raise ValueError
    return " ".join(x for x in (str(int(day)) if day else "", MONTHS[month - 1], year) if x)


def _plain_date(text: str) -> str:
    text = text.strip().rstrip(",")
    if re.fullmatch(r"\d{3,4}", text):
        return text
    if m := re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{3,4})", text):
        return _day_month_year(m[1], int(m[2]), m[3])
    if m := re.fullmatch(r"(\d{3,4})-(\d{1,2})-(\d{1,2})", text):
        return _day_month_year(m[3], int(m[2]), m[1])
    if m := re.fullmatch(r"(\d{1,2})[-/.](\d{3,4})", text):
        return _day_month_year("", int(m[1]), m[2])
    words = text.replace(",", " ").split()
    if len(words) == 3 and words[0].isdigit() and words[1].lower() in MONTH_NAMES and words[2].isdigit():
        return _day_month_year(words[0], MONTH_NAMES[words[1].lower()], words[2])
    if len(words) == 3 and words[0].lower() in MONTH_NAMES and words[1].isdigit() and words[2].isdigit():
        return _day_month_year(words[1], MONTH_NAMES[words[0].lower()], words[2])
    if len(words) == 2 and words[0].lower() in MONTH_NAMES and words[1].isdigit():
        return _day_month_year("", MONTH_NAMES[words[0].lower()], words[1])
    raise ValueError


def gedcom_date(text: str) -> str:
    """A date as people write it (12-3-1950, 12 maart 1950, omstreeks 1890, tussen 1880 en 1885) in GEDCOM form."""
    raw = " ".join(text.split())
    if not raw:
        return ""
    words = raw.split()
    try:
        if m := re.fullmatch(r"(?:bet|between|tussen)\s+(.+?)\s+(?:and|en)\s+(.+)", raw, re.I):
            return f"BET {_plain_date(m[1])} AND {_plain_date(m[2])}"
        for qualifier, spellings in QUALIFIERS.items():
            if words[0].lower() in spellings:
                return f"{qualifier} {_plain_date(' '.join(words[1:]))}"
        return _plain_date(raw)
    except (ValueError, IndexError):
        upper = raw.upper()
        if parse_date(upper).year is not None and all(w in MONTHS or w.isdigit() or w in (
            "ABT", "BEF", "AFT", "EST", "CAL", "BET", "AND", "FROM", "TO"
        ) for w in upper.split()):
            return upper
        raise BuildError(t("cannot read the date '{date}'; write it like 12-3-1950, 1950 or about 1890", date=text)) from None


def _ids(lines: list[str], letter: str) -> list[int]:
    return [int(m[1]) for line in lines if (m := re.match(rf"0 @{letter}(\d+)@ ", line.lstrip("﻿")))]


def next_id(lines: list[str], letter: str) -> str:
    return f"{letter}{max(_ids(lines, letter), default=0) + 1}"


def _trailer(lines: list[str]) -> int:
    for i in range(len(lines) - 1, -1, -1):
        if lines[i] == "0 TRLR":
            return i
    raise edit.EditError(t("no 0 TRLR line at the end of the tree"))


def source_record(lines: list[str], title: str) -> str:
    """The source record with this title, made when it does not exist yet."""
    for i, line in enumerate(lines):
        m = re.match(r"0 @(S\d+)@ SOUR", line.lstrip("﻿"))
        if m and i + 1 < len(lines) and lines[i + 1] == f"1 TITL {title}":
            return m[1]
    sid = next_id(lines, "S")
    edit.insert(lines, _trailer(lines), [f"0 @{sid}@ SOUR", *edit.text(1, "TITL", title)])
    return sid


def _citation(level: int, source_id: str | None, page: str) -> list[str]:
    return edit.source(level, source_id, page) if source_id and page else (
        [f"{level} SOUR @{source_id}@"] if source_id else []
    )


def add_person(
    lines: list[str],
    given: str,
    surname: str,
    sex: str = "U",
    events: list[Event] | None = None,
    occupation: str = "",
    note: str = "",
    source: str = "",
    page: str = "",
) -> str:
    if not (given or surname):
        raise BuildError(t("a person needs a given name or a surname"))
    sex = sex.upper()[:1] or "U"
    if sex not in "MFU":
        raise BuildError(t("sex is M, F or U, not '{sex}'", sex=sex))
    sid = source_record(lines, source) if source else None
    pid = next_id(lines, "I")
    record = [f"0 @{pid}@ INDI", f"1 NAME {given} /{surname}/".replace("  ", " "), f"1 SEX {sex}"]
    if given:
        record.append(f"2 GIVN {given}")
    if surname:
        record.append(f"2 SURN {surname}")
    for event in events or []:
        # "1 DEAT Y": the event is known to have happened, date and place are not.
        record.append(f"1 {event.tag}" if event.date or event.place else f"1 {event.tag} Y")
        if event.date:
            record.append(f"2 DATE {gedcom_date(event.date)}")
        if event.place:
            record.append(f"2 PLAC {event.place}")
        record += _citation(2, sid, page)
    if occupation:
        record += [f"1 OCCU {occupation}", *_citation(2, sid, page)]
    if note:
        record += edit.text(1, "NOTE", note)
    record += _citation(1, sid, page)
    edit.insert(lines, _trailer(lines), record)
    return pid


def _link(lines: list[str], pid: str, line: str) -> None:
    start = edit.record(lines, pid)
    end = edit.block_end(lines, start)
    if line not in lines[start:end]:
        edit.insert(lines, end, [line])


def _sex(lines: list[str], pid: str) -> str:
    start = edit.record(lines, pid)
    for line in lines[start + 1 : edit.block_end(lines, start)]:
        if line.startswith("1 SEX "):
            return line[6:].strip()
    return "U"


def add_family(
    lines: list[str],
    partners: list[str],
    children: list[str] | None = None,
    married: Event | None = None,
    source: str = "",
    page: str = "",
) -> str:
    """A family of one or two partners (the man as HUSB, the woman as WIFE) and their children."""
    if not 1 <= len(partners) <= 2:
        raise BuildError(t("a family has one or two partners"))
    sid = source_record(lines, source) if source else None
    fid = next_id(lines, "F")
    roles = {"M": "HUSB", "F": "WIFE"}
    record = [f"0 @{fid}@ FAM"]
    used: set[str] = set()
    for pid in partners:
        role = roles.get(_sex(lines, pid)) or ("WIFE" if "HUSB" in used else "HUSB")
        if role in used:
            role = "WIFE" if role == "HUSB" else "HUSB"
        used.add(role)
        record.append(f"1 {role} @{pid}@")
    for child in children or []:
        edit.record(lines, child)
        record.append(f"1 CHIL @{child}@")
    if married:
        record.append("1 MARR" if married.date or married.place else "1 MARR Y")
        if married.date:
            record.append(f"2 DATE {gedcom_date(married.date)}")
        if married.place:
            record.append(f"2 PLAC {married.place}")
        record += _citation(2, sid, page)
    record += _citation(1, sid, page)
    edit.insert(lines, _trailer(lines), record)
    for pid in partners:
        _link(lines, pid, f"1 FAMS @{fid}@")
    for child in children or []:
        _link(lines, child, f"1 FAMC @{fid}@")
    return fid


def add_child(lines: list[str], fid: str, child: str) -> None:
    start = edit.record(lines, fid)
    _link(lines, child, f"1 FAMC @{fid}@")
    end = edit.block_end(lines, start)
    if f"1 CHIL @{child}@" not in lines[start:end]:
        edit.insert(lines, end, [f"1 CHIL @{child}@"])
