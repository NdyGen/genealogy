"""A book of life stories along two patrilineal lines of one person: the father's and the mother's.

Each chapter is the life story from reports/life-stories/, followed by how the line runs down to the
chosen person and by the facts in the tree that support the story, each with its source.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

from lineage import i18n, kinship, settings
from lineage.gedcom import Event, Person, Tree
from lineage.i18n import t
from lineage.queue import possibly_living
from lineage.reports import _citation_text

# The book lives next to the life stories, so their relative image paths only need one extra hop.
_IMAGE = re.compile(r"(!\[[^\]]*\]\()(?!https?://|/)([^)]+\))")
_ITALIC_LINE = re.compile(r"^\*[^*].*\*$")
_EVENT_ORDER = [
    "BIRT",
    "CHR",
    "BAPM",
    "MARB",
    "MARR",
    "OCCU",
    "RESI",
    "CENS",
    "EVEN",
    "DEAT",
    "BURI",
    "CREM",
]


_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def _day(text: str) -> str:
    return " ".join(
        i18n.month(_MONTHS.index(part) + 1) if part in _MONTHS else part for part in text.split()
    )


def _qualified(qualifier: str, date: str) -> str:
    if qualifier in ("ABT", "EST", "CAL"):
        return t("about {date}", date=date)
    return t("before {date}", date=date) if qualifier == "BEF" else t("after {date}", date=date)


def plain_date(raw: str) -> str:
    """GEDCOM date phrase in plain words: 'BEF 2 SEP 1832' becomes 'before 2 September 1832'."""
    raw = raw.strip()
    m = re.fullmatch(r"(BET|FROM) (.+?) (AND|TO) (.+)", raw)
    if m:
        first, second = _day(m[2]), _day(m[4])
        if m[1] == "BET":
            return t("between {first} and {second}", first=first, second=second)
        return t("from {first} to {second}", first=first, second=second)
    m = re.fullmatch(r"(FROM|TO) (.+)", raw)
    if m:
        return t("from {date}", date=_day(m[2])) if m[1] == "FROM" else t("to {date}", date=_day(m[2]))
    m = re.fullmatch(r"(ABT|EST|CAL|BEF|AFT) (.+)", raw)
    if m:
        return _qualified(m[1], _day(m[2]))
    return _day(raw)


def years(person: Person, tree: Tree) -> str:
    """'(1832-1922)' for the line; nothing for people who may be alive."""
    if possibly_living(person, tree):
        return ""
    born = person.birth_date.year if person.birth_date and person.birth_date.year else None
    died = person.death_date.year if person.death_date and person.death_date.year else None
    if not born and not died:
        return ""
    return f"({born or '?'}-{died or '?'})"


@dataclass
class Chapter:
    person: Person
    generation: int
    story: str | None
    background: str | None


def patriline(tree: Tree, start: str | None) -> list[Person]:
    """start, his father, his father's father, ...; stops at the first unknown father."""
    line: list[Person] = []
    seen: set[str] = set()
    pid = start
    while pid and pid in tree.persons and pid not in seen:
        seen.add(pid)
        line.append(tree.persons[pid])
        father, _ = tree.parents(pid)
        pid = father.id if father else None
    return line


def _story(pid: str, stories: Path) -> tuple[str | None, str | None]:
    """Story body without its title, relation line and source tail; plus the background paragraph."""
    path = stories / f"{pid}.md"
    if not path.exists():
        return None, None
    lines = path.read_text(encoding="utf-8").splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    if lines and _ITALIC_LINE.match(lines[0].strip()):
        lines = lines[1:]
    tail: list[str] = []
    if "---" in (line.strip() for line in lines):
        cut = max(i for i, line in enumerate(lines) if line.strip() == "---")
        lines, tail = lines[:cut], lines[cut + 1 :]
    body = "\n".join(lines).strip()
    body = re.sub(r"^(#{2,5}) ", lambda m: "#" + m[1] + " ", body, flags=re.M)
    body = _IMAGE.sub(lambda m: m[1] + _rebase(m[2], stories), body)
    body = re.sub(r"\]\((I\d+)\.md\)", r"](#\1)", body)
    background = next((line for line in tail if line.startswith(("**Background", "**Achtergrond"))), None)
    return body, background


def _rebase(target: str, stories: Path) -> str:
    """Image paths are relative to the stories directory; the book sits in a sibling directory."""
    return f"../{stories.name}/{target}" if not target.startswith("../") else target


def _title(tree: Tree, person: Person, stories: Path) -> str:
    path = stories / f"{person.id}.md"
    if path.exists() and not possibly_living(person, tree):
        first = path.read_text(encoding="utf-8").splitlines()[:1]
        if first and first[0].startswith("# "):
            return first[0][2:].strip()
    return f"{person.name} {years(person, tree)}".strip()


def _event_text(event: Event) -> str:
    what = event.label if event.tag != "EVEN" else (event.value.split(":")[0] or t("event"))
    detail = event.value if event.tag in ("OCCU", "RESI") else ""
    if event.tag == "EVEN" and ":" in event.value:
        detail = event.value.split(":", 1)[1].strip()
    parts = [
        p for p in (plain_date(event.date.raw) if event.date else "", event.place, detail) if p
    ]
    return f"{what}: {', '.join(parts)}" if parts else what


def _sort_key(event: Event) -> tuple[int, int]:
    year = event.date.year if event.date and event.date.year else 9999
    order = _EVENT_ORDER.index(event.tag) if event.tag in _EVENT_ORDER else len(_EVENT_ORDER)
    return year, order


def facts(tree: Tree, person: Person) -> list[str]:
    """Every dated or placed fact of the person and his marriages, each with its sources."""
    events = [(e, "") for e in person.events]
    for family in tree.spouse_families(person.id):
        partner = tree.partner(family, person.id)
        suffix = " " + t("(with {name})", name=partner.name) if partner else ""
        events += [(e, suffix) for e in family.events]
    lines = []
    for event, suffix in sorted(events, key=lambda pair: _sort_key(pair[0])):
        sources = (
            "; ".join(_citation_text(tree, c) for c in event.citations) or t("no source recorded")
        )
        lines.append(f"- {_event_text(event)}{suffix}. " + t("Source: {sources}", sources=sources))
    return lines


def _line_to(tree: Tree, ancestor: Person, chain: list[Person], target: Person) -> list[str]:
    """The generations from ancestor down to the target, each with its relation to the target."""
    start = chain.index(ancestor)
    lines = []
    for person in reversed(chain[: start + 1]):
        relation = kinship.describe(tree, person.id, target.id) or t("kinship unknown")
        lines.append(
            f"{len(lines) + 1}. {person.name} {years(person, tree)} [{person.id}], {relation}".replace(
                "  ", " "
            )
        )
    lines.append(f"{len(lines) + 1}. {target.name} [{target.id}]")
    return lines


def _chapters(tree: Tree, line: list[Person], stories: Path) -> list[Chapter]:
    return [
        Chapter(
            person,
            gen,
            *(_story(person.id, stories) if not possibly_living(person, tree) else (None, None)),
        )
        for gen, person in enumerate(line, start=1)
    ]


def _render_chapter(
    tree: Tree,
    chapter: Chapter,
    chain: list[Person],
    target: Person,
    stories: Path,
    reports: Path,
) -> list[str]:
    person = chapter.person
    out = [f'<a id="{person.id}"></a>', "", f"## {_title(tree, person, stories)}", ""]
    if possibly_living(person, tree):
        out += [t("*Possibly living: no life story and no facts included.*"), ""]
    elif chapter.story:
        out += [chapter.story, ""]
    else:
        out += [
            t("*No life story has been written for this person yet. The facts below are established.*"),
            "",
        ]
    out += [t("### Line to {name}", name=target.name), "", *_line_to(tree, person, chain, target), ""]
    if not possibly_living(person, tree):
        fact_lines = facts(tree, person)
        out += [t("### Supporting facts"), ""]
        out += fact_lines or [t("- No facts with a date or place have been recorded yet.")]
        report = reports / f"{person.id}.md"
        if report.exists():
            out += ["", t("Full account: `{path}`.", path=report.as_posix())]
        if chapter.background:
            out += ["", chapter.background]
        out.append("")
    return out


def build(
    tree: Tree,
    target_id: str,
    stories: Path | None = None,
    reports: Path | None = None,
    oldest_first: bool = True,
    today: dt.date | None = None,
) -> str:
    stories = stories or settings.current().path("life_stories")
    reports = reports or settings.current().path("person_reports")
    target = tree.persons[target_id]
    father, mother = tree.parents(target_id)
    parts = [
        (
            t("Part I"),
            t("The paternal line of {name}", name=target.name),
            patriline(tree, father.id if father else None),
        ),
        (
            t("Part II"),
            t("{name}'s mother and her paternal line", name=target.name),
            ([mother] + patriline(tree, mother.id)[1:]) if mother else [],
        ),
    ]
    compiled = i18n.date(today or dt.date.today())
    out = [t("# Life stories of the ancestors of {name}", name=target.name), ""]
    out += [
        t(
            "*Compiled from the family tree research on {date}. Part I follows the father of {name} and his "
            "father, generation after generation. Part II starts with the mother and follows her father and his "
            "paternal line. Under each story it shows how the line runs to {name} and which facts in the tree "
            "support the story, each with its source.*",
            date=compiled,
            name=target.name,
        ),
        "",
        t("## Contents"),
        "",
    ]
    rendered: list[str] = []
    gaps: list[Person] = []
    for number, subtitle, line in parts:
        out.append(f"**{number}. {subtitle}**")
        out.append("")
        chapters = _chapters(tree, line, stories)
        ordered = list(reversed(chapters)) if oldest_first else chapters
        for chapter in ordered:
            p = chapter.person
            if possibly_living(p, tree):
                mark = " " + t("(living)")
            else:
                mark = "" if chapter.story else " " + t("(no story yet)")
            out.append(f"- [{_title(tree, p, stories)}](#{p.id}){mark}")
            if not chapter.story and not possibly_living(p, tree):
                gaps.append(p)
        if not line:
            out.append(t("- (no data)"))
        out.append("")
        rendered += [f"# {number}. {subtitle}", ""]
        for chapter in ordered:
            rendered += _render_chapter(tree, chapter, line, target, stories, reports)
    out += rendered
    if gaps:
        out += [t("# Still to write"), ""]
        out += [f"- {p.name} {years(p, tree)} [{p.id}]".replace("  ", " ") for p in gaps]
        out.append("")
    return "\n".join(out).rstrip() + "\n"
