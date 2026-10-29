"""Text reports in Dutch genealogical conventions (ancestor table, descendant table)."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from lineage.checks import Level, check, normalize
from lineage.gedcom import Citation, Event, Person, Tree
from lineage.i18n import t

SYMBOLS = {"BIRT": "*", "CHR": "~", "BAPM": "~", "DEAT": "†", "BURI": "□", "CREM": "□", "MARR": "x"}
_HTML_TAG = re.compile(r"<[^>]+>")


def roman(number: int) -> str:
    numerals = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    result = ""
    for value, numeral in numerals:
        while number >= value:
            result += numeral
            number -= value
    return result


def _event_short(event: Event) -> str:
    parts = [p for p in (event.date.raw if event.date else "", event.place) if p]
    return f"{SYMBOLS.get(event.tag, event.label)} {' '.join(parts)}".rstrip()


def lifespan(person: Person) -> str:
    birth = person.event("BIRT", "CHR", "BAPM")
    death = person.event("DEAT", "BURI", "CREM")
    parts = [_event_short(e) for e in (birth, death) if e and (e.date or e.place)]
    return f"({', '.join(parts)})" if parts else ""


def label(person: Person) -> str:
    return f"{person.name} [{person.id}] {lifespan(person)}".rstrip()


@dataclass(frozen=True)
class Ancestor:
    number: int
    person: Person
    same_as: int | None = None

    @property
    def generation(self) -> int:
        return self.number.bit_length()


def numbered_ancestors(tree: Tree, root_id: str, generations: int) -> list[Ancestor]:
    """Ancestors numbered by the Sosa-Stradonitz system; repeated ancestors (pedigree collapse)
    are listed once in full and referenced afterwards."""
    result: list[Ancestor] = []
    first_number: dict[str, int] = {}
    queue = [(1, root_id)]
    while queue:
        number, pid = queue.pop(0)
        person = tree.persons.get(pid)
        if not person:
            continue
        if pid in first_number:
            result.append(Ancestor(number, person, first_number[pid]))
            continue
        first_number[pid] = number
        result.append(Ancestor(number, person))
        if number.bit_length() < generations:
            father, mother = tree.parents(pid)
            if father:
                queue.append((2 * number, father.id))
            if mother:
                queue.append((2 * number + 1, mother.id))
    return sorted(result, key=lambda a: a.number)


def ancestor_table(tree: Tree, root_id: str, generations: int) -> str:
    lines = []
    current = 0
    for ancestor in numbered_ancestors(tree, root_id, generations):
        if ancestor.generation != current:
            current = ancestor.generation
            lines.append("\n" + t("Generation {roman}", roman=roman(current)))
        if ancestor.same_as:
            reference = t("{name}, see no. {number}", name=ancestor.person.name, number=ancestor.same_as)
            lines.append(f"{ancestor.number:>6}. {reference}")
        else:
            lines.append(f"{ancestor.number:>6}. {label(ancestor.person)}")
    return "\n".join(lines).lstrip("\n")


def descendant_table(tree: Tree, root_id: str, generations: int) -> str:
    lines: list[str] = []
    seen: set[str] = set()

    def walk(pid: str, generation: int) -> None:
        person = tree.persons[pid]
        indent = "    " * (generation - 1)
        if pid in seen:
            lines.append(
                f"{indent}{roman(generation)}. " + t("{name} [{pid}], see above", name=person.name, pid=pid)
            )
            return
        seen.add(pid)
        lines.append(f"{indent}{roman(generation)}. {label(person)}")
        for family in tree.spouse_families(pid):
            partner = tree.partner(family, pid)
            marriage = family.event("MARR")
            married = _event_short(marriage) if marriage else "x"
            partner_text = label(partner) if partner else t("(unknown partner)")
            lines.append(f"{indent}    {married}: {partner_text}")
            if generation < generations:
                for child in tree.children(family):
                    walk(child.id, generation + 1)

    if root_id in tree.persons:
        walk(root_id, 1)
    return "\n".join(lines)


def _citation_text(tree: Tree, citation: Citation) -> str:
    if not citation.source_id:
        return citation.page
    source = tree.sources.get(citation.source_id)
    title = source.title if source else t("unknown source")
    return f"{citation.source_id} {title}" + (f", {citation.page}" if citation.page else "")


def _plain(note: str) -> str:
    return _HTML_TAG.sub(" ", note).replace("&nbsp;", " ").strip()


def person_card(tree: Tree, pid: str) -> str:
    person = tree.persons[pid]
    lines = [f"{person.name} [{person.id}]", "  " + t("sex: {sex}", sex=person.sex)]

    for event in person.events:
        details = ", ".join(
            p for p in (event.date.raw if event.date else "", event.place, event.value) if p
        )
        lines.append(f"  {event.label}: {details or t('(yes)')}")
        lines += [
            "      " + t("source: {source}", source=_citation_text(tree, c)) for c in event.citations
        ]
    lines += [
        "  " + t("source: {source}", source=_citation_text(tree, c)) for c in person.citations
    ]

    father, mother = tree.parents(pid)
    if father or mother:
        lines.append("  " + t("parents:"))
        lines += [f"    {label(parent)}" for parent in (father, mother) if parent]

    for family in tree.spouse_families(pid):
        partner = tree.partner(family, pid)
        marriage = family.event("MARR")
        married = f" {_event_short(marriage)}" if marriage else ""
        lines.append(
            "  "
            + t(
                "family {id}: {partner}{married}",
                id=family.id,
                partner=label(partner) if partner else t("(unknown partner)"),
                married=married,
            )
        )
        lines += ["    " + t("child: {child}", child=label(child)) for child in tree.children(family)]

    for note in person.notes:
        lines.append("  " + t("note: {note}", note=_plain(note)))
    return "\n".join(lines)


def search(tree: Tree, query: str) -> list[Person]:
    words = normalize(query).split()
    matches = [p for p in tree.persons.values() if all(w in normalize(p.name) for w in words)]
    return sorted(matches, key=lambda p: (normalize(p.surname), normalize(p.given), birth_year(p)))


def birth_year(person: Person) -> int:
    return (person.birth_date.year if person.birth_date else None) or 0


def overview(tree: Tree) -> str:
    persons = list(tree.persons.values())
    sourced = sum(1 for p in persons if p.all_citations())
    years = [p.birth_date.year for p in persons if p.birth_date and p.birth_date.year]
    surnames = Counter(p.surname for p in persons if p.surname)
    findings = Counter(f.level for f in check(tree))

    lines = [
        t("persons:   {count}", count=len(persons)),
        t("families:  {count}", count=len(tree.families)),
        t("sources:   {count}", count=len(tree.sources)),
    ]
    if persons:
        lines.append(t("sourced:   {count} ({percent}%)", count=sourced, percent=100 * sourced // len(persons)))
    if years:
        lines.append(t("born:      {first} to {last}", first=min(years), last=max(years)))
    lines.append(
        t("checks:    ") + ", ".join(f"{findings[level]} {level.name.lower()}" for level in Level)
    )
    if surnames:
        lines.append(t("most common surnames:"))
        lines += [f"  {count:>5}  {name}" for name, count in surnames.most_common(10)]
    return "\n".join(lines)
