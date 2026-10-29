"""GEDCOM 5.5.1 reader covering what the research tooling needs; it never writes GEDCOM."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from lineage.dates import GedDate, parse_date
from lineage.i18n import t

EVENT_LABELS = {
    "BIRT": "born",
    "CHR": "baptized",
    "BAPM": "baptized",
    "DEAT": "died",
    "BURI": "buried",
    "CREM": "cremated",
    "ENGA": "engaged",
    "MARB": "marriage banns",
    "MARR": "married",
    "DIV": "divorced",
    "OCCU": "occupation",
    "RESI": "residing",
    "CENS": "census",
    "EMIG": "emigrated",
    "IMMI": "immigrated",
    "NATU": "naturalized",
    "EVEN": "event",
}


def event_label(tag: str) -> str:
    labels = {
        "BIRT": t("born"),
        "CHR": t("baptized"),
        "BAPM": t("baptized"),
        "DEAT": t("died"),
        "BURI": t("buried"),
        "CREM": t("cremated"),
        "ENGA": t("engaged"),
        "MARB": t("marriage banns"),
        "MARR": t("married"),
        "DIV": t("divorced"),
        "OCCU": t("occupation"),
        "RESI": t("residing"),
        "CENS": t("census"),
        "EMIG": t("emigrated"),
        "IMMI": t("immigrated"),
        "NATU": t("naturalized"),
        "EVEN": t("event"),
    }
    return labels.get(tag, tag.lower())


_LINE = re.compile(r"^\s*(\d+)\s+(?:(@[^@\s]+@)\s+)?(\S+)(?:\s(.*))?$")
_STRUCTURE_TAGS = (
    "FAMC|FAMS|HUSB|WIFE|CHIL|NAME|GIVN|SURN|NICK|SEX|SOUR|PAGE|QUAY|NOTE|OBJE|FILE|FORM|TITL"
    "|DATE|PLAC|AGE|TYPE|RIN|_UID|RELI|NATI|DSCR|MARL|ORDN"
)
_GLUED_LINE = re.compile(
    rf"^\d{{1,2}} (?:@[^@\s]+@ )?(?:{_STRUCTURE_TAGS}|{'|'.join(EVENT_LABELS)})(?: |$)"
)
_LINE_BREAK = re.compile(r"\r\n|\r|\n")
_NAME = re.compile(r"^(.*?)/(.*?)/(.*)$")


class GedcomError(ValueError):
    pass


@dataclass
class Node:
    level: int
    tag: str
    value: str = ""
    xref: str | None = None
    children: list[Node] = field(default_factory=list)

    def first(self, tag: str) -> Node | None:
        return next((child for child in self.children if child.tag == tag), None)

    def all(self, tag: str) -> list[Node]:
        return [child for child in self.children if child.tag == tag]

    def value_of(self, tag: str) -> str:
        child = self.first(tag)
        return child.value if child else ""


@dataclass
class Citation:
    source_id: str | None
    page: str = ""


@dataclass
class Event:
    tag: str
    date: GedDate | None = None
    place: str = ""
    value: str = ""
    citations: list[Citation] = field(default_factory=list)

    @property
    def label(self) -> str:
        return event_label(self.tag)


@dataclass
class Person:
    id: str
    given: str = ""
    surname: str = ""
    sex: str = "U"
    events: list[Event] = field(default_factory=list)
    child_of: list[str] = field(default_factory=list)
    spouse_in: list[str] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"{self.given} {self.surname}".strip() or "(unnamed)"

    def event(self, *tags: str) -> Event | None:
        for tag in tags:
            for event in self.events:
                if event.tag == tag:
                    return event
        return None

    @property
    def birth_date(self) -> GedDate | None:
        """Birth, or baptism when birth is unknown: baptism usually followed within days."""
        return _first_date(self, "BIRT", "CHR", "BAPM")

    @property
    def death_date(self) -> GedDate | None:
        """Death, or burial/cremation when death is unknown."""
        return _first_date(self, "DEAT", "BURI", "CREM")

    def all_citations(self) -> list[Citation]:
        return self.citations + [c for event in self.events for c in event.citations]


@dataclass
class Family:
    id: str
    husband: str | None = None
    wife: str | None = None
    children: list[str] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def partners(self) -> list[str]:
        return [pid for pid in (self.husband, self.wife) if pid]

    def event(self, tag: str) -> Event | None:
        return next((event for event in self.events if event.tag == tag), None)


@dataclass
class Source:
    id: str
    title: str = ""
    author: str = ""
    publication: str = ""


@dataclass
class Tree:
    persons: dict[str, Person] = field(default_factory=dict)
    families: dict[str, Family] = field(default_factory=dict)
    sources: dict[str, Source] = field(default_factory=dict)
    format_problems: list[str] = field(default_factory=list)

    def parents(self, pid: str) -> tuple[Person | None, Person | None]:
        person = self.persons.get(pid)
        if not person or not person.child_of:
            return None, None
        family = self.families.get(person.child_of[0])
        if not family:
            return None, None
        return self._get(family.husband), self._get(family.wife)

    def spouse_families(self, pid: str) -> list[Family]:
        person = self.persons.get(pid)
        if not person:
            return []
        return [self.families[fid] for fid in person.spouse_in if fid in self.families]

    def partner(self, family: Family, pid: str) -> Person | None:
        other = family.wife if family.husband == pid else family.husband
        return self._get(other)

    def children(self, family: Family) -> list[Person]:
        return [self.persons[cid] for cid in family.children if cid in self.persons]

    def _get(self, pid: str | None) -> Person | None:
        return self.persons.get(pid) if pid else None


def _first_date(person: Person, *tags: str) -> GedDate | None:
    for tag in tags:
        event = person.event(tag)
        if event and event.date:
            return event.date
    return None


def _pointer(value: str) -> str:
    return value.strip().strip("@")


def parse_nodes(text: str, problems: list[str] | None = None) -> list[Node]:
    """Lines that are not valid GEDCOM are kept as a continuation of the previous value
    (exporters leak raw newlines) and reported in `problems`; without it they raise."""
    roots: list[Node] = []
    stack: list[Node] = []
    for lineno, raw in enumerate(_LINE_BREAK.split(text.removeprefix("\ufeff")), 1):
        if not raw.strip():
            continue
        match = _LINE.match(raw)
        if not match or int(match[1]) > len(stack):
            if problems is None or not stack:
                raise GedcomError(t("line {lineno}: invalid GEDCOM line: {raw!r}", lineno=lineno, raw=raw))
            problems.append(t(
                    "line {lineno}: stray line without level or tag: {raw!r}", lineno=lineno, raw=raw.strip()
                ))
            stack[-1].value += "\n" + raw
            continue
        level = int(match[1])
        del stack[level:]
        tag, value = match[3].upper(), match[4] or ""

        if tag in ("CONC", "CONT") and stack:
            stack[-1].value += ("\n" if tag == "CONT" else "") + value
            continue

        if problems is not None and _GLUED_LINE.match(value):
            problems.append(t("line {lineno}: glued line after {tag}: {raw!r}", lineno=lineno, tag=tag, raw=raw.strip()))

        node = Node(level, tag, value, _pointer(match[2]) if match[2] else None)
        (stack[-1].children if stack else roots).append(node)
        stack.append(node)
    return roots


def _citations(node: Node) -> list[Citation]:
    result = []
    for sour in node.all("SOUR"):
        if sour.value.startswith("@"):
            result.append(Citation(_pointer(sour.value), sour.value_of("PAGE")))
        else:
            result.append(Citation(None, sour.value))
    return result


def _notes(node: Node, note_records: dict[str, str]) -> list[str]:
    result = []
    for note in node.all("NOTE"):
        if note.value.startswith("@"):
            result.append(note_records.get(_pointer(note.value), ""))
        else:
            result.append(note.value)
    return [text for text in result if text]


def _events(node: Node) -> list[Event]:
    events = []
    for child in node.children:
        if child.tag not in EVENT_LABELS:
            continue
        date = child.value_of("DATE")
        value = child.value if child.value != "Y" else ""
        if child.tag == "EVEN" and child.value_of("TYPE"):
            value = f"{child.value_of('TYPE')}: {value}".rstrip(": ")
        events.append(
            Event(
                tag=child.tag,
                date=parse_date(date) if date else None,
                place=child.value_of("PLAC"),
                value=value,
                citations=_citations(child),
            )
        )
    return events


def _person(node: Node, note_records: dict[str, str]) -> Person:
    person = Person(id=node.xref or "", sex=node.value_of("SEX") or "U")
    name = node.first("NAME")
    if name:
        match = _NAME.match(name.value)
        if match:
            person.given, person.surname = match[1].strip(), match[2].strip()
        else:
            person.given = name.value_of("GIVN") or name.value.strip()
            person.surname = name.value_of("SURN")
        person.citations.extend(_citations(name))
    person.citations.extend(_citations(node))
    person.events = _events(node)
    person.child_of = [_pointer(n.value) for n in node.all("FAMC")]
    person.spouse_in = [_pointer(n.value) for n in node.all("FAMS")]
    person.notes = _notes(node, note_records)
    return person


def _family(node: Node, note_records: dict[str, str]) -> Family:
    husband, wife = node.value_of("HUSB"), node.value_of("WIFE")
    return Family(
        id=node.xref or "",
        husband=_pointer(husband) if husband else None,
        wife=_pointer(wife) if wife else None,
        children=[_pointer(n.value) for n in node.all("CHIL")],
        events=_events(node),
        notes=_notes(node, note_records),
    )


def _repair_split_characters(nodes: list[Node]) -> None:
    """Some exporters (MyHeritage) split multi-byte UTF-8 characters across CONC lines;
    the bytes only form valid text once the lines are joined."""
    for node in nodes:
        node.value = node.value.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
        _repair_split_characters(node.children)


def parse(text: str) -> Tree:
    problems: list[str] = []
    roots = parse_nodes(text, problems)
    _repair_split_characters(roots)
    note_records = {n.xref: n.value for n in roots if n.tag == "NOTE" and n.xref}
    tree = Tree(format_problems=problems)
    seen: set[str] = set()
    for node in roots:
        if not node.xref:
            continue
        if node.xref in seen:
            problems.append(t("ID {xref} occurs more than once", xref=node.xref))
        seen.add(node.xref)
        if node.tag == "INDI":
            tree.persons[node.xref] = _person(node, note_records)
        elif node.tag == "FAM":
            tree.families[node.xref] = _family(node, note_records)
        elif node.tag == "SOUR":
            tree.sources[node.xref] = Source(
                id=node.xref,
                title=node.value_of("TITL"),
                author=node.value_of("AUTH"),
                publication=node.value_of("PUBL"),
            )
    return tree


def load(path: Path) -> Tree:
    return parse(path.read_bytes().decode("utf-8", "surrogateescape"))
