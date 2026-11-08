"""A few cited records of a round next to the facts they support, so the coordinator's own check is a
comparison, not a search. Weighted towards new parent links and corrections: a wrong record there spreads to
a whole branch or overwrites what was right."""

from __future__ import annotations

import collections
import random
import re
import shutil
import textwrap
from dataclasses import dataclass, field

from lineage import archive, verify, web
from lineage.gedcom import Node, Tree, parse, parse_nodes
from lineage.i18n import t

LINK, CORRECTION = "new link", "correction"
_WEIGHTS = {LINK: 3, CORRECTION: 3, verify.CONTRADICTED: 2, verify.PARTIAL: 2}
_BIRTH_TAGS = ("BIRT", "CHR", "BAPM")
_KINDS = ("oa", "delpher", "scan")


@dataclass
class Pick:
    kind: str
    ref: str
    checks: list[verify.Check] = field(default_factory=list)
    reasons: set[str] = field(default_factory=set)
    links: list[verify.Fact] = field(default_factory=list)

    @property
    def weight(self) -> int:
        return 1 + sum(_WEIGHTS.get(r, 0) for r in self.reasons)


def _content(node: Node) -> str:
    """The fact without its citations: what a correction changes."""
    return f"{node.tag} {node.value}\n" + "".join(_content(c) for c in node.children if c.tag != "SOUR")


def corrections(old: str, new: str) -> set[tuple[str, str]]:
    """(record, tag) of facts that stood in `old` with another date, place or value."""
    before: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    for record in parse_nodes(old, []):
        for child in record.children if record.xref else []:
            if child.tag in verify.FACT_TAGS:
                before[(record.xref, child.tag)].add(_content(child))
    return {
        (f.owner, f.tag) for f in verify.changed_facts(old, new)
        if (f.owner, f.tag) in before and _content(f.node) not in before[(f.owner, f.tag)]
    }  # fmt: skip


def candidates(old: str, new: str, tree: Tree, offline: bool = False) -> list[Pick]:
    """The round's cited records, one per record, with the reasons to look at them."""
    fixed = corrections(old, new)
    by_owner: dict[str, list[verify.Fact]] = collections.defaultdict(list)
    for fact in verify.facts(new):
        by_owner[fact.owner].append(fact)
    marked: list[tuple[verify.Fact, set[str], verify.Fact | None]] = [
        (f, {CORRECTION} if (f.owner, f.tag) in fixed else set(), None) for f in verify.changed_facts(old, new)
    ]
    # An uncited link rests on the child's baptism or birth record.
    for link in verify.parent_links(new, old):
        marked += [(f, {LINK}, link) for f in [link, *by_owner[link.owner]] if f is link or f.tag in _BIRTH_TAGS]
    picks: dict[tuple[str, str], Pick] = {}
    for fact, reasons, link in marked:
        for citation in fact.citations:
            kind, ref = verify.reference(citation)
            if kind not in _KINDS:
                continue
            pick = picks.setdefault((kind, ref), Pick(kind, ref))
            pick.reasons |= reasons
            if link and link.tag == "FAMC" and link is not fact and all(x.node is not link.node for x in pick.links):
                pick.links.append(link)
            if not any(c.fact.owner == fact.owner and verify._serial(c.fact.node) == verify._serial(fact.node)
                       for c in pick.checks):
                check = verify.check_citation(fact, citation, tree, offline)
                pick.checks.append(check)
                if check.outcome in _WEIGHTS:
                    pick.reasons.add(check.outcome)
    return list(picks.values())


def choose(picks: list[Pick], n: int, seed: str) -> list[Pick]:
    """n picks, weighted, the same ones for the same seed (the coordinator and the review agent see one
    sample)."""
    rng = random.Random(seed)
    keyed = sorted(picks, key=lambda p: rng.random() ** (1 / p.weight), reverse=True)
    return keyed[:n]


def sample(old: str, new: str, n: int, seed: str, offline: bool = False) -> str:
    tree = parse(new)
    chosen = choose(candidates(old, new, tree, offline), n, seed)
    if not chosen:
        return t("sample: no cited record in this round")
    width = min(72, max(40, (shutil.get_terminal_size((160, 40)).columns - 3) // 2))
    return "\n\n".join(render(i, p, tree, width, offline) for i, p in enumerate(chosen, 1))


# --- side by side -------------------------------------------------------------------------------------------


def _word(key: str) -> str:
    return {
        LINK: t("new link"), CORRECTION: t("correction"), verify.SUPPORTED: t("supported"),
        verify.PARTIAL: t("partly"), verify.CONTRADICTED: t("contradicted"), verify.UNRESOLVABLE: t("unresolvable"),
        verify.UNCHECKED: t("not comparable"), verify.UNREREAD: t("scan without reread marker"),
    }[key]  # fmt: skip


def _fact_lines(check: verify.Check, tree: Tree) -> list[str]:
    fact = check.fact
    person = tree.persons.get(fact.owner)
    lines = [f"{fact.label}: {person.name if person else _couple(fact.owner, tree)}"]
    if fact.tag == "FAMC":
        lines = _link_lines(fact, tree)
    elif fact.tag == "NAME":
        lines.append(fact.node.value)
    for tag in ("TYPE", "DATE", "PLAC", "AGE"):
        if value := fact.node.value_of(tag):
            lines.append(f"{tag} {value}")
    if fact.node.value and fact.tag not in ("NAME", "FAMC") and not fact.node.value.startswith("@"):
        lines.append(fact.node.value)
    lines.append(f"QUAY {check.citation.quay or '-'}: {check.citation.page}")
    return lines


def _link_lines(link: verify.Fact, tree: Tree) -> list[str]:
    child = tree.persons.get(link.owner)
    names = _couple(link.node.value.strip("@ "), tree)
    return [f"{link.label}: {child.name if child else link.owner}", t("parents: {names}", names=names)]


def _couple(fam: str, tree: Tree) -> str:
    family = tree.families.get(fam)
    return " x ".join(tree.persons[p].name for p in family.partners if p in tree.persons) if family else fam


def _record_lines(pick: Pick, tree: Tree, offline: bool) -> list[str]:
    if pick.kind == "oa":
        try:
            record = archive.show(pick.ref, offline=offline)
        except archive.ArchiveError as exc:
            return [str(exc)]
        lines = [" ".join(x for x in (record.event, record.date, record.place) if x)]
        lines += [", ".join(x for x in (record.institution, record.source_type, record.inventory and f"inv. {record.inventory}",
                                        record.deed and t("deed {deed}", deed=record.deed)) if x)]  # fmt: skip
        for person in record.persons:
            extra = [
                person.age and t("age {age}", age=person.age),
                person.birth and t("born {birth}", birth=person.birth),
                person.profession, person.residence,
            ]  # fmt: skip
            lines.append(f"{person.role or '?'}: {person.name}" + (f" ({', '.join(x for x in extra if x)})" if any(extra) else ""))
        lines += record.remarks
        return [*lines, record.url]
    if pick.kind == "delpher":
        try:
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", verify.delpher_text(pick.ref, offline)))
        except (archive.NotCached, web.WebError) as exc:
            return [str(exc)]
        return [*_excerpt(text, pick, tree), f"https://resolver.kb.nl/resolve?urn={pick.ref}"]
    # The lead's reading stands in the citation's NOTE or in the fact's own.
    notes = dict.fromkeys(
        _short(note) for c in pick.checks
        for note in [c.citation.note, *(n.value for n in c.fact.node.all("NOTE"))] if note
    )  # fmt: skip
    return [t("open the scan: {ref}", ref=pick.ref), *(notes or [t("no reading at the fact")])]


def _short(text: str, limit: int = 700) -> str:
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()
    return text if len(text) <= limit else text[:limit] + "..."


def _excerpt(text: str, pick: Pick, tree: Tree) -> list[str]:
    """The OCR text around the first surname of the fact it finds."""
    for check in pick.checks:
        for person in verify._fact_persons(check.fact, tree):
            surname = person.surname.split()[-1] if person.surname.split() else ""
            if surname and (m := re.search(re.escape(surname), text, re.I)):
                return [("..." if m.start() > 300 else "") + text[max(0, m.start() - 300): m.end() + 300] + "..."]
    return [text[:600] + "..."]


def _columns(left: list[str], right: list[str], width: int) -> list[str]:
    def wrapped(lines: list[str]) -> list[str]:
        return [part for line in lines for part in (textwrap.wrap(line, width) or [""])]

    left, right = wrapped(left), wrapped(right)
    rows = max(len(left), len(right))
    left += [""] * (rows - len(left))
    right += [""] * (rows - len(right))
    return [f"{a:<{width}} | {b}".rstrip() for a, b in zip(left, right, strict=True)]


def render(number: int, pick: Pick, tree: Tree, width: int, offline: bool = False) -> str:
    reasons = ", ".join(_word(r) for r in sorted(pick.reasons)) or t("routine")
    left = [line for check in pick.checks for line in [*_fact_lines(check, tree), ""]]
    left += [line for link in pick.links for line in [*_link_lines(link, tree), ""]]
    left = left[:-1]
    head = [f"{number}. [{reasons}] {pick.ref}", _columns([t("tree")], [t("record")], width)[0], "-" * (2 * width + 3)]
    outcomes = [
        f"verify: {check.fact.label} {_word(check.outcome)}" + (f": {'; '.join(check.details)}" if check.details else "")
        for check in pick.checks
    ]  # fmt: skip
    return "\n".join([*head, *_columns(left, _record_lines(pick, tree, offline), width), *outcomes])
