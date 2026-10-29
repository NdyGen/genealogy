"""Research queue for deep research per person, stored as a TSV so git can merge it line by line.

Parallel branches may each append or update lines; after a union merge the same person can
appear more than once, so loading keeps the most advanced status and `save` rewrites the file
deduplicated and sorted.
"""

from __future__ import annotations

import csv
import datetime as dt
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from lineage import kinship, paternal, settings
from lineage.gedcom import Person, Tree
from lineage.i18n import t

STATUSES = ("open", "in_progress", "done", "skipped")
STATUS_RANK = {"open": 0, "skipped": 1, "in_progress": 2, "done": 3}
LEGACY_COLUMNS = {
    "prioriteit": "priority",
    "ronde": "round",
    "door": "via",
    "reden": "reason",
    "toegevoegd": "added",
    "idreeks": "id_block",
    "rapport": "report",
}
LEGACY_STATUSES = {"bezig": "in_progress", "klaar": "done", "overgeslagen": "skipped"}
# Each research run gets its own block so parallel agents never hand out the same new ID.
ID_BLOCK_START = 800
ID_BLOCK_SIZE = 1000
# Records from the last hundred years are not public and the people may still be alive.
LIVING_CUTOFF_YEAR = 1926
MIN_PARENT_AGE = 12


class QueueError(ValueError):
    pass


@dataclass
class Item:
    id: str
    status: str = "open"
    priority: int = 5
    round: int = 1
    via: str = ""
    reason: str = ""
    added: str = ""
    id_block: str = ""
    report: str = ""

    @property
    def sort_key(self) -> tuple[int, int, int, str]:
        return (STATUS_RANK[self.status], self.round, self.priority, self.id)


FIELDS = [f.name for f in fields(Item)]


def load(path: Path | None = None) -> dict[str, Item]:
    path = path or settings.current().path("queue")
    items: dict[str, Item] = {}
    if not path.exists():
        return items
    with path.open(encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle, delimiter="\t"):
            row = {LEGACY_COLUMNS.get(key, key): value for key, value in raw.items()}
            status = row.get("status") or "open"
            item = Item(
                id=row["id"],
                status=LEGACY_STATUSES.get(status, status),
                priority=int(row.get("priority") or 5),
                round=int(row.get("round") or 1),
                via=row.get("via") or "",
                reason=row.get("reason") or "",
                added=row.get("added") or "",
                id_block=row.get("id_block") or "",
                report=row.get("report") or "",
            )
            if item.status not in STATUSES:
                raise QueueError(t("{path}: unknown status {status!r} for {pid}", path=path, status=item.status, pid=item.id))
            known = items.get(item.id)
            if known is None or _stronger(item, known):
                items[item.id] = _merge(known, item)
            else:
                items[item.id] = _merge(item, known)
    return items


def _block(item: Item) -> int:
    return int(item.id_block.split("-")[0]) if item.id_block else -1


def _stronger(new: Item, known: Item) -> bool:
    # A follow-up round gets a newer ID block; that line must win over the earlier "done".
    if new.id_block and known.id_block and new.id_block != known.id_block:
        return _block(new) > _block(known)
    return STATUS_RANK[new.status] > STATUS_RANK[known.status]


def _merge(weaker: Item | None, stronger: Item) -> Item:
    """Keep the stronger status but do not lose an ID block or report the other line had."""
    if weaker is None:
        return stronger
    return Item(
        **{
            **asdict(stronger),
            "id_block": stronger.id_block or weaker.id_block,
            "report": stronger.report or weaker.report,
            "priority": min(stronger.priority, weaker.priority),
            "round": min(stronger.round, weaker.round),
        }
    )


def save(items: dict[str, Item], path: Path | None = None) -> None:
    path = path or settings.current().path("queue")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for item in sorted(items.values(), key=lambda i: i.sort_key):
            writer.writerow(asdict(item))


def _latest_year(events) -> int | None:
    years = [
        e.date.latest or e.date.year for e in events if e.date and (e.date.latest or e.date.year)
    ]
    return min(years, default=None)


def _latest_birth(person: Person, tree: Tree | None) -> int | None:
    """Upper bound for the birth year: nobody is born after their own dated events or long before their children."""
    bounds = [_latest_year(person.events)]
    for family in tree.spouse_families(person.id) if tree else []:
        family_year = _latest_year(family.events)
        bounds.append(family_year - MIN_PARENT_AGE if family_year else None)
        for child in tree.children(family):
            child_year = _latest_year(child.events)
            bounds.append(child_year - MIN_PARENT_AGE if child_year else None)
    return min((b for b in bounds if b is not None), default=None)


def possibly_living(person: Person, tree: Tree | None = None) -> bool:
    if person.death_date or person.event("DEAT", "BURI", "CREM"):
        return False
    year = person.birth_date.year if person.birth_date else _latest_birth(person, tree)
    return year is None or year >= LIVING_CUTOFF_YEAR


def add(
    items: dict[str, Item],
    tree: Tree,
    pid: str,
    via: str = "",
    reason: str = "",
    priority: int = 5,
    round: int = 1,
    today: dt.date | None = None,
) -> tuple[Item, bool]:
    """Returns the item and whether it was newly added."""
    person = tree.persons.get(pid)
    if person is None:
        raise QueueError(t("person {pid} is not in the tree", pid=pid))
    if pid in items:
        return items[pid], False
    item = Item(
        id=pid,
        priority=priority,
        round=round,
        via=via,
        reason=reason,
        added=(today or dt.date.today()).isoformat(),
    )
    if possibly_living(person, tree):
        item.status = "skipped"
        item.reason = t("{reason}; possibly living, do not research", reason=reason).lstrip("; ")
    items[pid] = item
    return item, True


def direct_line(tree: Tree, root: str | None = None) -> set[str]:
    """The direct line: root (default the project's line root) and all its ancestors."""
    return set(kinship.ancestors(tree, root or settings.current().root_person))


def stem_rank(tree: Tree, stems: tuple[tuple[str, ...], ...] | None = None) -> dict[str, float]:
    """Rank per person: 0 for the first paternal line (men and their wives), 1 for the next, and so on;
    with "men-first" the wives of a line rank half a step after its men. Default: the project's stems."""
    rank: dict[str, float] = {}
    for nr, (_, start, *options) in enumerate(settings.current().stem_tuples if stems is None else stems):
        if start not in tree.persons:
            continue
        men = paternal.line(tree, start)
        wives_rank = nr + 0.5 if "men-first" in options else nr
        for man in men:
            rank.setdefault(man, nr)
        for man in men:
            for fam in tree.spouse_families(man):
                for partner in fam.partners:
                    rank.setdefault(partner, wives_rank)
    return rank


def next_open(
    items: dict[str, Item],
    tree: Tree | None = None,
    line: set[str] | None = None,
    stems: tuple[tuple[str, ...], ...] | None = None,
) -> Item | None:
    """With a tree, skips items that would clash with running research and puts the paternal
    lines (stems, default the project's) first; with line, only those and the paternal lines,
    whose wives always go first even outside the direct line."""
    stems = settings.current().stem_tuples if stems is None else stems
    rank = stem_rank(tree, stems) if tree else {}
    candidates = [
        i
        for i in items.values()
        if i.status == "open"
        and (line is None or i.id in line or i.id in rank)
        and (tree is None or not conflicts(items, tree, i.id))
    ]
    return (
        min(candidates, key=lambda i: (rank.get(i.id, len(stems)), i.sort_key))
        if candidates
        else None
    )


def _used_blocks(items: dict[str, Item]) -> set[int]:
    return {int(i.id_block.split("-")[0]) // ID_BLOCK_SIZE for i in items.values() if i.id_block}


def _families(tree: Tree, pid: str) -> set[str]:
    person = tree.persons.get(pid)
    return set(person.child_of + person.spouse_in) if person else set()


def conflicts(items: dict[str, Item], tree: Tree, pid: str) -> list[str]:
    """Running items that share a family with `pid`; both would edit the same FAM record."""
    mine = _families(tree, pid)
    return sorted(
        other.id
        for other in items.values()
        if other.status == "in_progress" and other.id != pid and mine & _families(tree, other.id)
    )


def start(
    items: dict[str, Item], tree: Tree, pid: str, force: bool = False, follow_up: bool = False
) -> Item:
    """With follow_up, a finished person gets a follow-up round with a fresh ID block."""
    item = items.get(pid)
    if item is None:
        raise QueueError(t("{pid} is not in the queue", pid=pid))
    allowed = ("open", "done") if follow_up else ("open",)
    if item.status not in allowed:
        raise QueueError(
            t(
                "{pid} has status {status}, not {allowed}",
                pid=pid,
                status=item.status,
                allowed=" or ".join(allowed),
            )
        )
    clash = conflicts(items, tree, pid)
    if clash and not force:
        raise QueueError(
            t("{pid} shares a family with running research {others}", pid=pid, others=", ".join(clash))
        )
    used_numbers = {
        int(x[1:]) // ID_BLOCK_SIZE
        for x in list(tree.persons) + list(tree.families) + list(tree.sources)
        if x[1:].isdigit()
    }
    block = ID_BLOCK_START
    while block in _used_blocks(items) or block in used_numbers:
        block += 1
    first = block * ID_BLOCK_SIZE + 1
    item.id_block = f"{first}-{first + ID_BLOCK_SIZE - 2}"
    item.status = "in_progress"
    return item


def finish(items: dict[str, Item], pid: str, report: str) -> Item:
    item = items.get(pid)
    if item is None:
        raise QueueError(t("{pid} is not in the queue", pid=pid))
    item.status = "done"
    item.report = report
    return item
