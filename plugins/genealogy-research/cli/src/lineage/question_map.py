"""Where the open research questions sit in the pedigree of the reference person, as data for a heatmap page.

The page leaves this machine (an artifact on claude.ai), so it only names people who died before 1900, like the
other exceptions in CLAUDE.md; everyone else is an anonymous count.
"""

from __future__ import annotations

import datetime as dt
import html
import json
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path

from lineage import i18n
from lineage.gedcom import Person, Tree
from lineage.gramps import CHOICE, EXCLUDED_HEADINGS, ON_SITE, ONLINE, Question, read_questions
from lineage.i18n import t
from lineage.queue import _latest_birth, possibly_living

LINE_GENERATION = 4
CUTOFF_YEAR = 1900
TEMPLATE = Path(__file__).with_name("question_map.html")
KINDS = (CHOICE, ONLINE, ON_SITE)
LEGACY_HISTORY_COLUMNS = {
    "datum": "date",
    "keuze": "choice",
    "ter plaatse": "on_site",
    "opgelost": "solved",
    "gaten": "gaps",
    "voorouders": "ancestors",
}


def is_nameable(person: Person, tree: Tree) -> bool:
    if possibly_living(person, tree):
        return False
    year = person.birth_date.year if person.birth_date and person.birth_date.year else _latest_birth(person, tree)
    died = person.death_date.year if person.death_date and person.death_date.year else None
    return (died or year or CUTOFF_YEAR) < CUTOFF_YEAR


def _years(person: Person) -> str:
    born = person.birth_date.year if person.birth_date and person.birth_date.year else None
    died = person.death_date.year if person.death_date and person.death_date.year else None
    return f"{born or '?'}-{died or '?'}" if born or died else ""


def ahnentafel_numbers(tree: Tree, root: str, max_gen: int = 30) -> dict[int, str]:
    """Ahnentafel numbers: root is 1, the father of n is 2n, the mother 2n+1."""
    found = {1: root}
    queue = deque([1])
    while queue:
        n = queue.popleft()
        if n.bit_length() > max_gen:
            continue
        father, mother = tree.parents(found[n])
        for k, parent in ((2 * n, father), (2 * n + 1, mother)):
            if parent:
                found[k] = parent.id
                queue.append(k)
    return found


def _nearest_ancestor(tree: Tree, pid: str, ancestors: set[str]) -> str | None:
    """A question about a sibling, child or second spouse belongs to the side branch of the nearest ancestor."""
    seen, queue = {pid}, deque([(pid, 0)])
    while queue:
        x, d = queue.popleft()
        if x in ancestors and x != pid:
            return x
        if d >= 4:
            continue
        neighbours = [p.id for p in tree.parents(x) if p]
        for fam in tree.spouse_families(x):
            neighbours += [p for p in fam.partners if p]
        for n in neighbours:
            if n not in seen:
                seen.add(n)
                queue.append((n, d + 1))
    return None


def _stem_name(tree: Tree, numbers: dict[int, str], names: set[str], k: int) -> str:
    """The surname of the line, from the first nameable man up its paternal path (the great-great-grandparents
    themselves are often still too recent to name)."""
    while k in numbers:
        p = tree.persons[numbers[k]]
        if numbers[k] in names and p.surname:
            return p.surname
        k *= 2
    return ""


@dataclass
class Tally:
    own: Counter = field(default_factory=Counter)
    side_branch: Counter = field(default_factory=Counter)
    questions: dict[str, list[dict]] = field(default_factory=dict)


def count_questions(questions: list[Question], tree: Tree, ancestors: set[str], names: set[str]) -> tuple[Tally, Counter]:
    tally = Tally()
    region: Counter = Counter()
    for q in questions:
        if q.done or q.chapter.startswith(EXCLUDED_HEADINGS) or q.kind not in KINDS:
            continue
        kind = q.kind
        region[(q.group or t("Other"), kind)] += 1
        touched: dict[str, str] = {}
        for pid in q.ids:
            if pid in ancestors:
                touched.setdefault(pid, "own")
            elif pid.startswith("I") and pid in tree.persons:
                anchor = _nearest_ancestor(tree, pid, ancestors)
                if anchor:
                    touched.setdefault(anchor, "side_branch")
        readable = all(p in names for p in q.ids if p.startswith("I"))
        for pid, how in touched.items():
            (tally.own if how == "own" else tally.side_branch)[pid] += 1
            if readable:
                tally.questions.setdefault(pid, []).append({"kind": kind, "how": how, "text": q.title})
    return tally, region


def build(tree: Tree, questions_text: str, root: str, today: dt.date | None = None) -> dict:
    numbers = ahnentafel_numbers(tree, root)
    ancestors = set(numbers.values())
    names = {pid for pid in ancestors | set(tree.persons) if is_nameable(tree.persons[pid], tree)}
    questions = read_questions(questions_text)
    tally, region = count_questions(questions, tree, ancestors, names)
    first = 1 << LINE_GENERATION
    lines = []
    for k in range(first, 2 * first):
        label = _stem_name(tree, numbers, names, k) or t("line {number}", number=k - first + 1)
        lines.append({"number": k, "label": label, "paternal": k == first})
    persons: dict[str, dict] = {}
    cells: dict[str, dict] = {}
    for n, pid in numbers.items():
        gen = n.bit_length() - 1
        if gen < LINE_GENERATION:
            continue
        line = (n >> (gen - LINE_GENERATION)) - first
        p = tree.persons[pid]
        parents = [x for x in tree.parents(pid) if x]
        gap = 0 if possibly_living(p, tree) else 2 - len(parents)
        cell = cells.setdefault(f"{gen}:{line}", {"open": 0, "gaps": 0, "known": 0, "persons": []})
        cell["open"] += tally.own[pid] + tally.side_branch[pid]
        cell["gaps"] += gap
        cell["known"] += 1
        cell["persons"].append(pid)
        if pid not in persons:
            visible = pid in names
            persons[pid] = {
                "name": p.name if visible else None,
                "years": _years(p) if visible else "",
                "own": tally.own[pid],
                "side_branch": tally.side_branch[pid],
                "gap": gap,
                "questions": tally.questions.get(pid, []) if visible else [],
            }
    open_questions = [q for q in questions if not q.done and q.kind in KINDS]
    totals = {
        "date": (today or dt.date.today()).isoformat(),
        "open": len(open_questions),
        **{s: sum(1 for q in open_questions if q.kind == s) for s in KINDS},
        "solved": sum(1 for q in questions if q.done),
        "gaps": sum(p["gap"] for p in persons.values()),
        "ancestors": len(ancestors) - 1,
    }
    return {
        "root": root,
        "lines": lines,
        "generations": max((n.bit_length() - 1 for n in numbers), default=0),
        "first_generation": LINE_GENERATION,
        "cells": cells,
        "persons": persons,
        "regions": [{"group": g, "kind": s, "count": a} for (g, s), a in sorted(region.items())],
        "kinds": list(KINDS),
        "totals": totals,
    }


def update_history(path: Path, totals: dict) -> list[dict]:
    fields = list(totals)
    rows = []
    if path.exists():
        header, *lines = path.read_text(encoding="utf-8").splitlines()
        columns = [LEGACY_HISTORY_COLUMNS.get(c, c) for c in header.split("\t")]
        rows = [dict(zip(columns, r.split("\t"), strict=False)) for r in lines if r.strip()]
    rows = [r for r in rows if r.get("date") != totals["date"]] + [{k: str(v) for k, v in totals.items()}]
    path.write_text("\t".join(fields) + "\n" + "".join("\t".join(r.get(k, "") for k in fields) + "\n" for r in rows),
                   encoding="utf-8")
    return [{k: (v if k == "date" else int(v or 0)) for k, v in r.items()} for r in rows]


def labels() -> dict:
    """Every visible text of the page, in the output language."""
    return {
        "locale": {"nl": "nl-NL"}.get(i18n.language(), "en-GB"),
        "title": t("Question map ancestor table"),
        "heading": t("Where the open questions are"),
        "intro": t(
            "Each row is a generation, each column one of the sixteen lines that start at the "
            "great-great-grandparents. The darker the cell, the more there is left to research. "
            "Pick a cell for its people and their questions."
        ),
        "measure": t("Measure"),
        "measure_open": t("Open questions"),
        "measure_gaps": t("Missing parents"),
        "measure_known": t("Known ancestors"),
        "regions_heading": t("By region and kind of question"),
        "regions_intro": t(
            'All open questions from the question list, including those about side branches and questions '
            'without a person. "Online" the assistant can do itself, "on site" needs an archive visit or a '
            'better scan, "choice" waits for a decision.'
        ),
        "region": t("Region"),
        "total": t("total"),
        "progress_heading": t("Progress"),
        "progress_intro": t("Each time the map is updated, a data point is added."),
        "footer": t(
            "Names and questions appear only for people who died before 1900; more recent and possibly "
            "living people count as a number, without a name. Questions about a brother, sister, child or "
            "second partner count towards the nearest ancestor as a side branch."
        ),
        "terms": [
            "",
            t("parents"),
            t("grandparents"),
            t("great-grandparents"),
            t("great-great-grandparents"),
            t("great-great-great-grandparents"),
            t("great-great-great-great-grandparents"),
            t("great-great-great-great-great-grandparents"),
            t("great-great-great-great-great-great-grandparents"),
            t("great-great-great-great-great-great-great-grandparents"),
            t("great-great-great-great-great-great-great-great-grandparents"),
            t("great-great-great-great-great-great-great-great-great-grandparents"),
            t("great-great-great-great-great-great-great-great-great-great-grandparents"),
        ],
        "generation": t("generation {n}"),
        "stat_open": t("open questions"),
        "stat_online": t("to research online"),
        "stat_on_site": t("on site or better scan"),
        "stat_choice": t("waiting for a choice"),
        "stat_solved": t("solved"),
        "stat_gaps": t("missing parents"),
        "as_of": t("As of {date}: {ancestors} known ancestors over {generations} generations."),
        "fathers_side": t("Father's side"),
        "mothers_side": t("Mother's side"),
        "cell": t("{line}, generation {generation}: {value} {measure}"),
        "most_open": t("Most open questions"),
        "pick_cell": t("Pick a cell in the map to see the people in that generation and line."),
        "detail_eyebrow": t("Generation {generation} · {term}"),
        "detail_line": t("Line {label}"),
        "chip_open": t("{count} open"),
        "chip_gaps": t("{count} missing parents"),
        "chip_known": t("{known} known of {total}"),
        "anonymous_one": t("{count} recent person without a name."),
        "anonymous_many": t("{count} recent people without a name."),
        "show_one": t("Show {count} question"),
        "show_many": t("Show {count} questions"),
        "side_branch": t("side branch"),
        "own": t("{count} own"),
        "chip_side_branch": t("{count} side branch"),
        "parent_unknown": t("parent unknown"),
        "parents_unknown": t("parents unknown"),
        "kinds": {
            "choice": t("choice"),
            "online": t("online"),
            "on_site": t("on site"),
        },
        "trend_open": t("open"),
        "trend_solved": t("solved"),
        "trend_gaps": t("missing parents"),
        "trend_aria": t("Progress of open questions, solved questions and missing parents"),
    }


def write(data: dict, history: list[dict], out: Path, title: str = "") -> None:
    data = {**data, "history": history}
    texts = labels()
    page = TEMPLATE.read_text(encoding="utf-8")
    for key, text in texts.items():
        if isinstance(text, str):
            page = page.replace(f"[[{key}]]", html.escape(text))
    page = page.replace("__LABELS__", _script_json(texts)).replace("__DATA__", _script_json(data))
    eyebrow = html.escape(
        t("{title} · ancestor table from {root}", title=title or t("Family research"), root=data["root"])
    )
    out.write_text(page.replace("__EYEBROW__", eyebrow), encoding="utf-8")


def _script_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
