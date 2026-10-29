"""Graphviz DOT output. Couples are joined through a family node so children hang below both."""

from __future__ import annotations

from lineage.gedcom import Person, Tree
from lineage.reports import numbered_ancestors

FILL = {"M": "#dbe9f6", "F": "#f6dbe6"}


def _years(person: Person) -> str:
    birth = person.birth_date.year if person.birth_date else None
    death = person.death_date.year if person.death_date else None
    if not birth and not death:
        return ""
    return f"{birth or '?'}–{death or ''}"


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def ancestors(tree: Tree, root_id: str, generations: int) -> tuple[set[str], set[str]]:
    persons = {a.person.id for a in numbered_ancestors(tree, root_id, generations)}
    families = {
        tree.persons[pid].child_of[0]
        for pid in persons
        if tree.persons[pid].child_of and any(p.id in persons for p in tree.parents(pid) if p)
    }
    return persons, families


def descendants(tree: Tree, root_id: str, generations: int) -> tuple[set[str], set[str]]:
    persons: set[str] = set()
    families: set[str] = set()
    frontier = [root_id] if root_id in tree.persons else []
    for generation in range(1, generations + 1):
        persons.update(frontier)
        next_frontier = []
        for pid in frontier:
            for family in tree.spouse_families(pid):
                families.add(family.id)
                persons.update(family.partners)
                if generation < generations:
                    next_frontier += [c.id for c in tree.children(family) if c.id not in persons]
        frontier = next_frontier
    persons &= tree.persons.keys()
    return persons, families


def to_dot(tree: Tree, persons: set[str], families: set[str]) -> str:
    lines = [
        "digraph tree {",
        "  rankdir=TB;",
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10];',
        "  edge [arrowhead=none];",
    ]
    for pid in sorted(persons):
        person = tree.persons[pid]
        text = f"{person.name}\n{_years(person)}".strip()
        fill = FILL.get(person.sex, "#eeeeee")
        lines.append(f"  {_quote(pid)} [label={_quote(text)}, fillcolor={_quote(fill)}];")
    for fid in sorted(families):
        family = tree.families[fid]
        lines.append(f"  {_quote(fid)} [shape=point, width=0.08];")
        lines += [f"  {_quote(pid)} -> {_quote(fid)};" for pid in family.partners if pid in persons]
        lines += [f"  {_quote(fid)} -> {_quote(cid)};" for cid in family.children if cid in persons]
    lines.append("}")
    return "\n".join(lines) + "\n"
