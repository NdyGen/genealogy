"""Plausibility checks. Date checks only fire when a conflict is certain given the date ranges."""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from enum import IntEnum

from lineage.dates import GedDate, years_between
from lineage.gedcom import Event, Family, Person, Tree
from lineage.i18n import t

MAX_AGE = 105
MIN_PARENT_AGE = 13
MAX_MOTHER_AGE = 50
MAX_FATHER_AGE = 75
MIN_MARRIAGE_AGE = 14
DUPLICATE_YEAR_SPAN = 2
SOURCED_EVENTS = ("BIRT", "CHR", "BAPM", "DEAT", "BURI", "MARR")


class Level(IntEnum):
    ERROR = 1
    WARNING = 2
    INFO = 3


@dataclass(frozen=True)
class Finding:
    level: Level
    subject: str
    message: str


def check(tree: Tree) -> list[Finding]:
    findings = [Finding(Level.ERROR, "GEDCOM", problem) for problem in tree.format_problems]
    findings += _references(tree)
    for person in tree.persons.values():
        findings += _person(tree, person)
    for family in tree.families.values():
        findings += _family(tree, family)
    findings += _duplicates(tree)
    return sorted(findings, key=lambda f: (f.level, _id_key(f.subject), f.message))


def _id_key(subject: str) -> tuple[str, int]:
    prefix = subject.rstrip("0123456789")
    number = subject[len(prefix) :]
    return prefix, int(number) if number else 0


def _references(tree: Tree) -> list[Finding]:
    findings = []
    for person in tree.persons.values():
        for fid in person.child_of:
            family = tree.families.get(fid)
            if not family:
                findings.append(Finding(Level.ERROR, person.id, t("child of unknown family {fid}", fid=fid)))
            elif person.id not in family.children:
                findings.append(
                    Finding(
                        Level.ERROR,
                        person.id,
                        t("refers to family {fid}, which does not list them as a child", fid=fid),
                    )
                )
        for fid in person.spouse_in:
            family = tree.families.get(fid)
            if not family:
                findings.append(Finding(Level.ERROR, person.id, t("partner in unknown family {fid}", fid=fid)))
            elif person.id not in family.partners:
                findings.append(
                    Finding(
                        Level.ERROR,
                        person.id,
                        t("refers to family {fid}, which does not list them as a partner", fid=fid),
                    )
                )
        for citation in person.all_citations():
            if citation.source_id and citation.source_id not in tree.sources:
                findings.append(
                    Finding(
                        Level.ERROR,
                        person.id,
                        t("refers to unknown source {source}", source=citation.source_id),
                    )
                )

    for family in tree.families.values():
        for pid in family.partners:
            partner = tree.persons.get(pid)
            if not partner:
                findings.append(Finding(Level.ERROR, family.id, t("unknown partner {pid}", pid=pid)))
            elif family.id not in partner.spouse_in:
                findings.append(
                    Finding(
                        Level.ERROR,
                        family.id,
                        t("partner {pid} does not refer back to this family", pid=pid),
                    )
                )
        for cid in family.children:
            child = tree.persons.get(cid)
            if not child:
                findings.append(Finding(Level.ERROR, family.id, t("unknown child {cid}", cid=cid)))
            elif family.id not in child.child_of:
                findings.append(
                    Finding(
                        Level.ERROR,
                        family.id,
                        t("child {cid} does not refer back to this family", cid=cid),
                    )
                )
    return findings


def _unreadable_dates(subject: str, events: list[Event]) -> list[Finding]:
    return [
        Finding(
            Level.WARNING,
            subject,
            t("unreadable date '{date}' for {event}", date=event.date.raw, event=event.label),
        )
        for event in events
        if event.date and event.date.year is None
    ]


def _person(tree: Tree, person: Person) -> list[Finding]:
    findings = _unreadable_dates(person.id, person.events)
    birth, death = person.birth_date, person.death_date

    births = sum(1 for event in person.events if event.tag == "BIRT")
    if births > 1:
        findings.append(Finding(Level.WARNING, person.id, t("birth recorded {count} times", count=births)))
    deaths = sum(1 for event in person.events if event.tag == "DEAT")
    if deaths > 1:
        findings.append(Finding(Level.WARNING, person.id, t("death recorded {count} times", count=deaths)))

    if birth and death:
        low, high = years_between(birth, death)
        if high is not None and high < 0:
            findings.append(
                Finding(
                    Level.ERROR,
                    person.id,
                    t("died ({death}) before birth ({birth})", death=death, birth=birth),
                )
            )
        elif low is not None and low > MAX_AGE:
            findings.append(
                Finding(
                    Level.WARNING,
                    person.id,
                    t("died at an age of at least {low} years", low=low),
                )
            )

    if not person.all_citations():
        findings.append(Finding(Level.INFO, person.id, t("no citation at all")))
    else:
        unsourced = [e.label for e in person.events if e.tag in SOURCED_EVENTS and not e.citations]
        if unsourced:
            findings.append(Finding(Level.INFO, person.id, t("without source: {events}", events=", ".join(unsourced))))

    if len(tree.persons) > 1 and not person.child_of and not person.spouse_in:
        findings.append(Finding(Level.INFO, person.id, t("not connected to other persons")))
    return findings


def _family(tree: Tree, family: Family) -> list[Finding]:
    findings = _unreadable_dates(family.id, family.events)
    marriage = family.event("MARR")
    marriage_date = marriage.date if marriage else None
    partners = [p for p in (tree.persons.get(pid) for pid in family.partners) if p]

    for partner in partners:
        if marriage_date:
            findings += _marriage(family.id, partner, marriage_date)
        for child in tree.children(family):
            if child.birth_date:
                findings += _parenthood(family.id, partner, child, child.birth_date)
    return findings


def _marriage(subject: str, partner: Person, marriage: GedDate) -> list[Finding]:
    findings = []
    if partner.birth_date:
        _, high = years_between(partner.birth_date, marriage)
        if high is not None and high < MIN_MARRIAGE_AGE:
            findings.append(
                Finding(
                    Level.WARNING,
                    subject,
                    t("{name} married at {high} years old at most", name=partner.name, high=high),
                )
            )
    if partner.death_date:
        low, _ = years_between(partner.death_date, marriage)
        if low is not None and low > 0:
            findings.append(
                Finding(
                    Level.ERROR,
                    subject,
                    t(
                        "marriage ({marriage}) after the death of {name}",
                        marriage=marriage,
                        name=partner.name,
                    ),
                )
            )
    return findings


def _parenthood(subject: str, parent: Person, child: Person, born: GedDate) -> list[Finding]:
    findings = []
    if parent.birth_date:
        low, high = years_between(parent.birth_date, born)
        if high is not None and high < MIN_PARENT_AGE:
            findings.append(
                Finding(
                    Level.ERROR,
                    subject,
                    t(
                        "{parent} was at most {high} years old at the birth of {child}",
                        parent=parent.name,
                        high=high,
                        child=child.name,
                    ),
                )
            )
        max_age = MAX_MOTHER_AGE if parent.sex == "F" else MAX_FATHER_AGE
        if low is not None and low > max_age:
            findings.append(
                Finding(
                    Level.WARNING,
                    subject,
                    t(
                        "{parent} was at least {low} years old at the birth of {child}",
                        parent=parent.name,
                        low=low,
                        child=child.name,
                    ),
                )
            )
    if parent.death_date:
        low, _ = years_between(parent.death_date, born)
        # A father can die before the birth; a gap of a full calendar year cannot be explained.
        allowed = 0 if parent.sex == "F" else 1
        if low is not None and low > allowed:
            findings.append(
                Finding(
                    Level.ERROR,
                    subject,
                    t(
                        "{child} born ({born}) after the death of {parent}",
                        child=child.name,
                        born=born,
                        parent=parent.name,
                    ),
                )
            )
    return findings


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold().strip()


def _duplicates(tree: Tree) -> list[Finding]:
    by_name: dict[str, list[Person]] = defaultdict(list)
    for person in tree.persons.values():
        if person.given or person.surname:
            by_name[normalize(person.name)].append(person)

    findings = []
    for group in by_name.values():
        dated = [p for p in group if p.birth_date and p.birth_date.year]
        for i, first in enumerate(dated):
            for second in dated[i + 1 :]:
                close = abs(first.birth_date.year - second.birth_date.year) <= DUPLICATE_YEAR_SPAN
                if (
                    close
                    and not _name_reused(first, second)
                    and not _separate_records(first, second)
                    and not _different_parents(first, second)
                ):
                    findings.append(
                        Finding(
                            Level.WARNING,
                            first.id,
                            t(
                                "possibly the same person as {pid} ({name})",
                                pid=second.id,
                                name=second.name,
                            ),
                        )
                    )
    return findings


def _name_reused(first: Person, second: Person) -> bool:
    """Parents often gave the name of a deceased child to the next one."""
    for earlier, later in ((first, second), (second, first)):
        if earlier.death_date and later.birth_date:
            low, _ = years_between(earlier.death_date, later.birth_date)
            if low is not None and low >= 0:
                return True
    return False


def _birth_records(person: Person) -> set[tuple[str | None, str]]:
    return {
        (c.source_id, c.page)
        for event in person.events
        if event.tag in ("BIRT", "CHR", "BAPM")
        for c in event.citations
        if any(word in c.page for word in ("archive", "record", "archief", "akte"))
    }


def _separate_records(first: Person, second: Person) -> bool:
    """Two different birth or baptism records prove two children, e.g. a name given twice."""
    a, b = _birth_records(first), _birth_records(second)
    return bool(a and b and not a & b)


def _different_parents(first: Person, second: Person) -> bool:
    """Cousins named after the same grandparent share name and age but not their parents."""
    return bool(
        first.child_of and second.child_of and not set(first.child_of) & set(second.child_of)
    )
