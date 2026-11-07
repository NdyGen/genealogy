"""Re-fetch the records a fact cites and compare them with the fact.

A round's own rules ("proof or nothing") are prompt text; this reads the cited record again and compares
event, date, place and names. Per citation the outcome is one of OUTCOMES. A fact with a QUAY 3 citation
counts as proven: a contradiction there, or no QUAY 3 citation that resolves, is an error.
"""

from __future__ import annotations

import collections
import datetime as dt
import hashlib
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from lineage import archive, web
from lineage.checks import normalize
from lineage.dates import parse_date
from lineage.gedcom import EVENT_LABELS, Node, Person, Tree, parse, parse_nodes
from lineage.i18n import t

SUPPORTED, PARTIAL, CONTRADICTED, UNRESOLVABLE, UNCHECKED, UNREREAD = (
    "supported", "partial", "contradicted", "unresolvable", "unchecked", "unreread",
)  # fmt: skip
OUTCOMES = (SUPPORTED, PARTIAL, CONTRADICTED, UNRESOLVABLE, UNCHECKED, UNREREAD)
FACT_TAGS = frozenset(EVENT_LABELS) | {"NAME", "FAMC"}
DELPHER_CACHE = Path.home() / ".cache" / "lineage" / "delpher"

_OA = re.compile(r"openarchieven\.nl/(?:[a-z]{2}/)?(?:record/)?([a-z0-9_]+)[:/]([0-9a-f]{8}-[0-9a-f-]{20,})", re.I)
_DELPHER = re.compile(r"(?:resolver\.kb\.nl/resolve\?urn=|[?&]identifier=)((?:ddd|MMKB\w*|KBNRC\w*|abcddd):[^&\s;,)]+)")
_SCAN = re.compile(
    r"\b(?:scan|crop|uitsnede|transkribus|rat):\s*\S+"
    r"|\S*scans/\S+\.(?:jpe?g|png|tiff?|webp)\b",
    re.I,
)
# The form leads already write for RAT protocols: "RAT <fonds> (<name>) inv. <n> p. <n> (scans <n>-<n>)".
_RAT = re.compile(r"\bRAT (\d+)\b.*?\binv\. (\w+).*?\bscans? (\d+)", re.I)
_REREAD = re.compile(r"reread by (?:the )?lead|(?:na|her)gelezen door (?:de )?leider", re.I)
_URL = re.compile(r"https?://\S+")
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
_PLAIN_DATE = re.compile(rf"^(?:(\d{{1,2}}) )?(?:({'|'.join(_MONTHS)}) )?(\d{{3,4}})$")
_PREFIXES = frozenset({"van", "de", "der", "den", "het", "ter", "ten", "te", "la", "le", "du", "d", "v", "vd", "in", "op", "t", "s"})
# Records name a child in Latin or in an older spelling; the tree in the spoken form.
_GIVEN_FORMS = {
    "jan": "johannes", "joannes": "johannes", "johan": "johannes", "hannes": "johannes",
    "hendrik": "henricus", "hendricus": "henricus", "henrick": "henricus", "hendrick": "henricus",
    "pieter": "petrus", "peter": "petrus", "piet": "petrus",
    "willem": "wilhelmus", "guilielmus": "wilhelmus", "gulielmus": "wilhelmus",
    "adriaan": "adrianus", "ariaan": "adrianus", "arie": "adrianus",
    "jacob": "jacobus", "jacques": "jacobus", "cornelis": "cornelius", "kees": "cornelius",
    "anna": "anna", "anneke": "anna", "maria": "maria", "marie": "maria", "mie": "maria",
    "catharina": "catharina", "catrina": "catharina", "trijntje": "catharina",
    "elisabeth": "elisabeth", "lijsbeth": "elisabeth", "isabella": "elisabeth",
    "johanna": "johanna", "jenneke": "johanna", "jantje": "johanna",
    "gerrit": "gerardus", "gerard": "gerardus", "dirk": "theodorus", "dirck": "theodorus",
    "klaas": "nicolaas", "nicolaus": "nicolaas", "claes": "nicolaas",
    "huibert": "hubertus", "hubert": "hubertus", "antonie": "antonius", "antoon": "antonius",
    "francis": "franciscus", "frans": "franciscus", "michiel": "michael", "lambert": "lambertus",
}  # fmt: skip
# Record event types that are the same event as the GEDCOM tag, and ones that bound it (baptism after birth).
_SAME = {
    "BIRT": {"Geboorte"}, "CHR": {"Doop"}, "BAPM": {"Doop"}, "DEAT": {"Overlijden"},
    "BURI": {"Begraven"}, "MARR": {"Huwelijk", "Trouwen"}, "MARB": {"Ondertrouw"}, "ENGA": {"Ondertrouw"},
}  # fmt: skip
_NEAR = {
    "BIRT": ({"Doop"}, 0, 400), "CHR": ({"Geboorte"}, -400, 0), "BAPM": ({"Geboorte"}, -400, 0),
    "DEAT": ({"Begraven"}, 0, 30), "BURI": ({"Overlijden"}, -30, 0),
    "MARR": ({"Ondertrouw"}, -120, 0), "MARB": ({"Huwelijk", "Trouwen"}, 0, 120),
}  # fmt: skip
_PRINCIPAL = {
    "Geboorte": {"Kind"}, "Doop": {"Kind", "Dopeling"}, "Overlijden": {"Overledene"},
    "Begraven": {"Overledene"}, "Huwelijk": {"Bruidegom", "Bruid"}, "Trouwen": {"Bruidegom", "Bruid"},
    "Ondertrouw": {"Bruidegom", "Bruid"},
}  # fmt: skip
_PARENT_ROLES = re.compile(r"^(?:Vader|Moeder)\b", re.I)
_CHILD_ROLES = {"Kind", "Dopeling", "Bruidegom", "Bruid", "Overledene", "Geregistreerde"}


@dataclass
class Citation:
    source: str
    page: str
    quay: str
    note: str

    @property
    def text(self) -> str:
        return f"{self.page}\n{self.note}"


@dataclass
class Fact:
    owner: str
    tag: str
    node: Node
    citations: list[Citation]

    @property
    def label(self) -> str:
        return f"{self.owner} {self.tag}" + (f" @{self.node.value.strip('@')}@" if self.tag == "FAMC" else "")


@dataclass
class Check:
    fact: Fact
    citation: Citation
    ref: str
    outcome: str
    details: list[str] = field(default_factory=list)


@dataclass
class Result:
    checks: list[Check] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        found = collections.Counter(c.outcome for c in self.checks)
        return {o: found[o] for o in OUTCOMES}

    def summary(self) -> str:
        counts = self.counts()
        return t(
            "verify: {total} citations: {supported} supported, {partial} partly, {contradicted} contradicted, "
            "{unresolvable} unresolvable, {unchecked} not comparable, {unreread} scans without reread marker",
            total=len(self.checks), **counts,
        )  # fmt: skip

    def text(self) -> str:
        lines = [f"ERROR: {m}" for m in self.errors] + [f"WARNING: {m}" for m in self.warnings]
        return "\n".join([*lines, self.summary()])


# --- facts and citations ------------------------------------------------------------------------------------


def _citations(node: Node) -> list[Citation]:
    found = []
    for sour in node.all("SOUR"):
        notes = "\n".join(n.value for n in sour.all("NOTE"))
        found.append(Citation(sour.value.strip("@ "), sour.value_of("PAGE") or sour.value, sour.value_of("QUAY"), notes))
    return found


def _serial(node: Node) -> str:
    return f"{node.level} {node.tag} {node.value}\n" + "".join(_serial(c) for c in node.children)


def facts(text: str) -> list[Fact]:
    found = []
    for record in parse_nodes(text, []):
        if record.tag not in ("INDI", "FAM") or not record.xref:
            continue
        for child in record.children:
            if child.tag in FACT_TAGS and (cites := _citations(child)):
                found.append(Fact(record.xref, child.tag, child, cites))
    return found


def changed_facts(old: str, new: str) -> list[Fact]:
    """Facts of `new` whose structure, citations included, is not in `old` for the same record."""
    before: dict[str, set[str]] = collections.defaultdict(set)
    for fact in facts(old) if old else []:
        before[fact.owner].add(_serial(fact.node))
    return [f for f in facts(new) if _serial(f.node) not in before[f.owner]]


def reference(citation: Citation) -> tuple[str, str]:
    """(kind, reference) of a citation; kind is oa, delpher, scan, url or '' for free text."""
    if m := _OA.search(citation.page):
        return "oa", f"{m[1].lower()}:{m[2].lower()}"
    if m := _DELPHER.search(citation.page):
        return "delpher", m[1]
    if m := _RAT.search(citation.page):
        return "scan", f"rat:{m[1]}-{m[2]}/{m[3]}"
    if m := _SCAN.search(citation.text):
        return "scan", m[0]
    if m := _URL.search(citation.page):
        return "url", m[0].rstrip(".,;)")
    return "", ""


# --- comparing ----------------------------------------------------------------------------------------------


def _tokens(text: str) -> list[str]:
    return re.sub(r"[^a-z]+", " ", normalize(text)).split()


def _given_key(word: str) -> str:
    return _GIVEN_FORMS.get(word, word)


def _similar(a: str, b: str) -> bool:
    return a == b or (len(a) > 2 and len(b) > 2 and SequenceMatcher(None, a, b).ratio() >= 0.8)


def name_score(person: Person, record_name: str) -> int:
    """2: given name and surname match, 1: one of them, 0: neither."""
    words = _tokens(record_name)
    if not words:
        return 0
    given = [_given_key(w) for w in _tokens(person.given)]
    given_ok = bool(given) and any(_similar(given[0], _given_key(w)) for w in words)
    surname = "".join(w for w in _tokens(person.surname) if w not in _PREFIXES)
    tails = {"".join(w for w in words[i:] if w not in _PREFIXES) for i in range(1, len(words))}
    surname_ok = bool(surname) and any(_similar(surname, tail) for tail in tails if tail)
    return int(given_ok) + int(surname_ok)


def _best(person: Person, record: archive.Record, roles: set[str] | None = None) -> tuple[int, archive.RecordPerson | None]:
    best: tuple[int, archive.RecordPerson | None] = (0, None)
    for candidate in record.persons:
        if roles is not None and candidate.role not in roles:
            continue
        score = name_score(person, candidate.name)
        if score > best[0]:
            best = (score, candidate)
    return best


def _find(person: Person, record: archive.Record, tree: Tree) -> tuple[int, archive.RecordPerson | None]:
    """The record person who is `person`; a wife is often only "the wife of <husband>"."""
    score, found = _best(person, record)
    if found:
        return score, found
    principal = _PRINCIPAL.get(record.event, set())
    for family in tree.spouse_families(person.id):
        partner = tree.partner(family, person.id)
        if partner and (match := _best(partner, record))[0] == 2:
            others = [p for p in record.persons if p is not match[1] and p.role in principal]
            return 1, (others[0] if others else match[1] if match[1].role in principal else None)
    return 0, None


def _plain(raw: str) -> tuple[int | None, int | None, int] | None:
    if m := _PLAIN_DATE.match(raw.strip().upper()):
        return (int(m[1]) if m[1] else None, _MONTHS.index(m[2]) + 1 if m[2] else None, int(m[3]))
    return None


def _date_text(parts: tuple[int | None, int | None, int | None]) -> str:
    return "-".join(str(p) for p in parts if p)


def _days(parts: tuple[int | None, int | None, int | None]) -> int | None:
    day, month, year = parts
    if not (day and month and year):
        return None
    try:
        return dt.date(year, month, day).toordinal()
    except ValueError:
        return None


def compare_date(raw: str, record: tuple[int | None, int | None, int | None]) -> bool | None:
    """True when the record date fits the fact date, False when it cannot, None when nothing to compare."""
    if not raw or not record[2]:
        return None
    if plain := _plain(raw):
        return all(a is None or b is None or a == b for a, b in zip(plain, record, strict=True))
    date = parse_date(raw)
    if date.earliest is None and date.latest is None:
        return None
    return (date.earliest is None or record[2] >= date.earliest) and (date.latest is None or record[2] <= date.latest)


def _near(raw: str, record: tuple[int | None, int | None, int | None], low: int, high: int) -> bool | None:
    """The record's event lies between low and high days after the fact's event."""
    plain = _plain(raw)
    if plain is None:
        # A range ("BEF 13 JAN 1733", from the baptism) only bounds the year.
        date = parse_date(raw) if raw else None
        if not date or not record[2] or (date.earliest is None and date.latest is None):
            return None
        return (date.earliest is None or record[2] >= date.earliest - 1) and (
            date.latest is None or record[2] <= date.latest + 1
        )
    fact, other = _days(plain), _days(record)
    if fact is None or other is None:
        return low // 365 - 1 <= record[2] - plain[2] <= high // 365 + 1 if record[2] else None
    return low <= other - fact <= high


def _place_key(text: str) -> str:
    return "".join(_tokens(text.split(",")[0]))


def compare_place(fact: str, record: str) -> bool | None:
    a, b = _place_key(fact), _place_key(record)
    if not a or not b:
        return None
    return a in b or b in a or _similar(a, b)


@dataclass
class _Comparison:
    agree: list[str] = field(default_factory=list)
    differ: list[str] = field(default_factory=list)
    conflict: list[str] = field(default_factory=list)

    def outcome(self) -> str:
        if self.conflict:
            return CONTRADICTED
        if self.differ:
            return PARTIAL
        return SUPPORTED if self.agree else UNCHECKED

    def details(self) -> list[str]:
        return list(dict.fromkeys(self.conflict + self.differ))


def _fact_persons(fact: Fact, tree: Tree) -> list[Person]:
    if fact.owner in tree.persons:
        return [tree.persons[fact.owner]]
    family = tree.families.get(fact.owner)
    return [tree.persons[p] for p in family.partners if p in tree.persons] if family else []


def compare_record(fact: Fact, record: archive.Record, tree: Tree) -> _Comparison:
    c = _Comparison()
    if fact.tag == "FAMC":
        return _compare_link(fact, record, tree, c)
    persons = _fact_persons(fact, tree)
    date_raw = fact.node.value_of("DATE")
    place = fact.node.value_of("PLAC")
    principal_roles = _PRINCIPAL.get(record.event, set())
    for person in persons:
        score, found = _find(person, record, tree)
        if not found:
            c.differ.append(t("{name} not found in the record", name=person.name))
            continue
        principal = found.role in principal_roles
        if fact.tag in _SAME and principal and record.event in _SAME[fact.tag]:
            match = compare_date(date_raw, record.date_parts)
            if match is False:
                # Burial registers often index the day the burial was reported, a few days off.
                close = _near(date_raw, record.date_parts, -10, 10)
                (c.differ if close else c.conflict).append(t(
                    "date: {fact} in the tree, {record} in the record",
                    fact=date_raw, record=_date_text(record.date_parts)))
            elif match:
                c.agree.append("date")
            if (same_place := compare_place(place, record.place)) is False:
                c.differ.append(t("place: {fact} in the tree, {record} in the record", fact=place, record=record.place))
            elif same_place:
                c.agree.append("place")
        elif fact.tag in _NEAR and principal and record.event in _NEAR[fact.tag][0]:
            _, low, high = _NEAR[fact.tag]
            match = _near(date_raw, record.date_parts, low, high)
            if match is False:
                c.differ.append(t("date: {fact} in the tree does not fit {event} {record} in the record",
                                  fact=date_raw, event=record.event, record=_date_text(record.date_parts)))
            elif match:
                c.agree.append("date")
        elif fact.tag in ("BIRT", "CHR", "BAPM") and found.birth_date[2]:
            if compare_date(date_raw, found.birth_date) is False:
                c.differ.append(t("birth: {fact} in the tree, {record} in the record",
                                  fact=date_raw, record=_date_text(found.birth_date)))
            else:
                c.agree.append("birth")
        elif fact.tag == "BIRT" and found.age.isdigit() and record.date_parts[2]:
            born = record.date_parts[2] - int(found.age)
            if compare_date(date_raw, (None, None, born)) is False and compare_date(date_raw, (None, None, born - 1)) is False:
                c.differ.append(t("age: {age} in the record ({year}) points to birth in {born}, the tree has {fact}",
                                  age=found.age, year=record.date_parts[2], born=born, fact=date_raw))
            else:
                c.agree.append("age")
        elif fact.tag == "OCCU" and fact.node.value:
            if _similar_text(fact.node.value, found.profession):
                c.agree.append("occupation")
            elif found.profession:
                c.differ.append(t("occupation: {fact} in the tree, {record} in the record",
                                  fact=fact.node.value, record=found.profession))
        elif fact.tag == "RESI" and place:
            if compare_place(place, found.residence or record.place):
                c.agree.append("residence")
            elif found.residence:
                c.differ.append(t("residence: {fact} in the tree, {record} in the record",
                                  fact=place, record=found.residence))
        elif fact.tag == "NAME" and score == 2:
            c.agree.append("name")
        elif fact.tag == "NAME":
            c.differ.append(t("name: {fact} in the tree, {record} in the record", fact=person.name, record=found.name))
    return c


def _similar_text(a: str, b: str) -> bool:
    x, y = "".join(_tokens(a)), "".join(_tokens(b))
    return bool(x and y) and (x in y or y in x or _similar(x, y))


def _compare_link(fact: Fact, record: archive.Record, tree: Tree, c: _Comparison) -> _Comparison:
    child = tree.persons.get(fact.owner)
    family = tree.families.get(fact.node.value.strip("@ "))
    if not child or not family:
        return c
    _, found = _best(child, record, _CHILD_ROLES)
    if not found:
        c.differ.append(t("child {name} not found in the record", name=child.name))
        return c
    parent_roles = {p.role for p in record.persons if _PARENT_ROLES.match(p.role)}
    for pid in family.partners:
        parent = tree.persons.get(pid)
        if not parent:
            continue
        _, match = _best(parent, record, parent_roles)
        if match:
            c.agree.append(match.role)
        else:
            c.differ.append(t("parent {name} not found in the record", name=parent.name))
    return c


# --- sources ------------------------------------------------------------------------------------------------


def delpher_text(urn: str, offline: bool = False) -> str:
    cache = DELPHER_CACHE / (hashlib.sha1(urn.encode()).hexdigest() + ".xml")
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    if offline:
        raise archive.NotCached(urn)
    data = web.fetch(f"https://resolver.kb.nl/resolve?urn={urn}:ocr").decode("utf-8", "replace")
    if "<text" not in data[:500]:
        raise web.WebError(t("{urn}: no OCR text", urn=urn))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(data, encoding="utf-8")
    return data


def compare_text(fact: Fact, text: str, tree: Tree) -> _Comparison:
    """A newspaper is no index: look for the names and the year in its OCR text."""
    c = _Comparison()
    words = set(_tokens(re.sub(r"<[^>]+>", " ", text)))
    joined = "".join(_tokens(text))
    for person in _fact_persons(fact, tree) or [p for p in [tree.persons.get(fact.owner)] if p]:
        surname = "".join(w for w in _tokens(person.surname) if w not in _PREFIXES)
        given = _tokens(person.given)[:1]
        if surname and surname in joined:
            c.agree.append("surname")
        elif surname:
            c.differ.append(t("{name}: surname not in the OCR text", name=person.name))
        if given and given[0] not in words:
            c.differ.append(t("{name}: given name not in the OCR text", name=person.name))
    date = parse_date(fact.node.value_of("DATE")) if fact.node.value_of("DATE") else None
    if date and date.year:
        if str(date.year) in text:
            c.agree.append("year")
        else:
            c.differ.append(t("year {year} not in the OCR text", year=date.year))
    return c


def check_citation(fact: Fact, citation: Citation, tree: Tree, offline: bool = False) -> Check:
    kind, ref = reference(citation)
    if kind == "oa":
        try:
            record = archive.show(ref, offline=offline)
        except archive.NotCached:
            return Check(fact, citation, ref, UNCHECKED, [t("not in the cache")])
        except archive.RecordNotFound as exc:
            return Check(fact, citation, ref, UNRESOLVABLE, [str(exc)])
        except archive.ArchiveError as exc:
            return Check(fact, citation, ref, UNCHECKED, [str(exc)])
        comparison = compare_record(fact, record, tree)
        return Check(fact, citation, ref, comparison.outcome(), comparison.details())
    if kind == "delpher":
        try:
            text = delpher_text(ref, offline)
        except (archive.NotCached, web.WebError) as exc:
            return Check(fact, citation, ref, UNCHECKED, [str(exc)])
        comparison = compare_text(fact, text, tree)
        return Check(fact, citation, ref, comparison.outcome(), comparison.details())
    if kind == "scan":
        reread = _REREAD.search(citation.text) or _REREAD.search("\n".join(n.value for n in fact.node.all("NOTE")))
        return Check(fact, citation, ref, UNCHECKED if reread else UNREREAD)
    if kind == "url":
        return Check(fact, citation, ref, UNCHECKED)
    return Check(fact, citation, citation.page[:60], UNRESOLVABLE)


def verify(old: str, new: str, offline: bool = False, everything: bool = False) -> Result:
    """Check the facts `new` adds or changes against `old` (every fact with `everything`)."""
    tree = parse(new)
    result = Result()
    for fact in facts(new) if everything else changed_facts(old, new):
        checks = [check_citation(fact, c, tree, offline) for c in fact.citations]
        result.checks += checks
        _judge(fact, checks, result)
    return result


def _judge(fact: Fact, checks: list[Check], result: Result) -> None:
    proven = [c for c in checks if c.citation.quay == "3"]
    for check in checks:
        where = f"{fact.label} ({check.ref or '?'})"
        detail = "; ".join(check.details)
        if check.outcome == CONTRADICTED:
            target = result.errors if check.citation.quay == "3" else result.warnings
            target.append(t("{where}: the record contradicts the fact: {detail}", where=where, detail=detail))
        elif check.outcome == PARTIAL:
            result.warnings.append(t("{where}: partly supported: {detail}", where=where, detail=detail))
        elif check.outcome == UNREREAD:
            result.warnings.append(t("{where}: rests on a scan without the lead's reread marker", where=where))
    if proven and all(c.outcome == UNRESOLVABLE for c in proven):
        result.errors.append(t("{fact}: proven (QUAY 3), but no citation resolves to a record, scan or URL",
                               fact=fact.label))


TSV_COLUMNS = ("record", "fact", "quay", "reference", "outcome", "details")


def tsv(result: Result) -> str:
    rows = ["\t".join(TSV_COLUMNS)]
    for c in result.checks:
        values = (c.fact.owner, c.fact.label.split(" ", 1)[1], c.citation.quay, c.ref, c.outcome, "; ".join(c.details))
        rows.append("\t".join(v.replace("\t", " ").replace("\n", " ") for v in values))
    return "\n".join(rows) + "\n"
