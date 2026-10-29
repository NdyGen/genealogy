"""The paternal line of the project's start person and the notice to the user when it grows by a generation."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from lineage import settings
from lineage.gedcom import Person, Tree
from lineage.i18n import t


def line(tree: Tree, start: str) -> list[str]:
    """From start up to the oldest known father."""
    ids = [start]
    while True:
        father, _ = tree.parents(ids[-1])
        if not father or father.id in ids:
            return ids
        ids.append(father.id)


def read_state(path: Path) -> list[str] | None:
    if not path.exists() or not path.read_text().strip():
        return None
    return path.read_text().split()


def write_state(path: Path, ids: list[str]) -> None:
    path.write_text(" ".join(ids) + "\n")


def new_generations(old: list[str], new: list[str]) -> list[str]:
    """Generations above the old top; empty unless the old line is still the base of the new one."""
    if len(new) <= len(old) or new[: len(old)] != old:
        return []
    return new[len(old) :]


def _life_dates(p: Person) -> str:
    parts = []
    for label, tags in (
        (t("born/baptised"), ("BIRT", "CHR", "BAPM")),
        (t("died/buried"), ("DEAT", "BURI")),
    ):
        e = p.event(*tags)
        if e and (e.date or e.place):
            parts.append(f"{label} {' '.join(x for x in (str(e.date or ''), e.place) if x)}".strip())
    return "; ".join(parts) or t("no life dates recorded")


def draft(
    tree: Tree,
    old: list[str],
    new: list[str],
    recipient: str,
    directory: Path | None = None,
    today: dt.date | None = None,
) -> Path:
    project = settings.current()
    directory = directory or project.path("requests")
    today = today or dt.date.today()
    added = new_generations(old, new)
    top = tree.persons[new[-1]]
    start = tree.persons[new[0]]
    surname = start.surname or start.name
    lines = [
        f"{project.sender_name or t('Hello')},",
        "",
        t(
            "The {surname} paternal line (from {name}, {id}) has grown by {added} generation(s). "
            "It now has {total} generations.",
            surname=surname,
            name=start.name,
            id=start.id,
            added=len(added),
            total=len(new),
        ),
        "",
        t("New in the line:"),
    ]
    for pid in added:
        p = tree.persons[pid]
        lines.append(f"- {p.name} ({pid}): {_life_dates(p)}")
        report = project.rel("person_reports") / f"{pid}.md"
        if (project.root / report).exists():
            lines.append("  " + t("report: {path}", path=report))
    previous = tree.persons.get(old[-1])
    lines += [
        "",
        t(
            "Until now {name} ({id}) was the oldest known father.",
            name=previous.name if previous else old[-1],
            id=old[-1],
        ),
        t(
            "His father is now {name} ({id}). The evidence is in the report of {old} or {id} and in {log}.",
            name=tree.persons[added[0]].name,
            id=added[0],
            old=old[-1],
            log=project.rel("log"),
        ),
        "",
        t("Regards,"),
        t("the research assistant"),
        "",
    ]
    header = [
        "---",
        f"to: {recipient}",
        f"institution: {project.sender_name or recipient} ({t('paternal line notice')})",
        "subject: "
        + t("{surname} paternal line extended: {name} ({id})", surname=surname, name=top.name, id=top.id),
        f"persons: {' '.join([old[-1], *added])}",
        f"created: {today.isoformat()}",
        "status: draft",
        "---",
    ]
    path = directory / f"{today.isoformat()}-paternal-{top.id.lower()}.md"
    path.write_text("\n".join(header + lines), encoding="utf-8")
    return path
