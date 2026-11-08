"""Gold-standard evaluation of research rounds.

A gold set (TOML) lists persons whose facts and parents were checked against scans. `exam` strips those
facts and parent links from a tree, a round on that tree has to find them again, and `score` compares the
round's tree with the gold set: precision and recall of facts and parent links, how often each QUAY held,
and lookups of possibly living persons in the round's transcripts (the rule allows none).

    [[person]]
    id = "I12"
    tags = ["BIRT", "CHR", "DEAT"]   # the gold is complete for these tags
    note = "why this person is in the set"
    facts = [{ tag = "CHR", date = "3 MAR 1712", place = "Breda", source = "<record URL or scan>" }]
    parents = [{ role = "father", name = "Jan Dekkers", born = 1680 }, { role = "mother", name = "Kee Smit" }]
"""

from __future__ import annotations

import collections
import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from lineage import verify
from lineage.checks import normalize
from lineage.gedcom import Person, Tree, parse, parse_nodes
from lineage.i18n import t
from lineage.queue import possibly_living

RIGHT, VAGUE, WRONG, MISSING = "right", "vague", "wrong", "missing"


@dataclass
class GoldFact:
    tag: str
    date: str = ""
    place: str = ""
    source: str = ""


@dataclass
class GoldParent:
    role: str
    name: str
    born: int | None = None


@dataclass
class GoldPerson:
    id: str
    tags: list[str]
    facts: list[GoldFact] = field(default_factory=list)
    parents: list[GoldParent] = field(default_factory=list)
    note: str = ""


def load(path: Path) -> list[GoldPerson]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    persons = []
    for raw in data.get("person", []):
        facts = [GoldFact(**f) for f in raw.get("facts", [])]
        persons.append(GoldPerson(
            id=raw["id"], tags=raw.get("tags") or sorted({f.tag for f in facts}), facts=facts,
            parents=[GoldParent(**p) for p in raw.get("parents", [])], note=raw.get("note", ""),
        ))  # fmt: skip
    return persons


# --- the exam -----------------------------------------------------------------------------------------------


def exam(text: str, gold: list[GoldPerson]) -> str:
    """`text` without the gold persons' facts of the gold tags and, where the gold names parents, without
    their parent link (FAMC and the family's CHIL). Line endings stay as they are."""
    strip = {p.id: set(p.tags) | ({"FAMC"} if p.parents else set()) for p in gold}
    orphans = {p.id for p in gold if p.parents}
    out, record, skipping = [], "", False
    for line in text.splitlines(keepends=True):
        parts = line.strip().split(" ", 2)
        level = int(parts[0]) if parts[0].isdigit() else 99
        if level == 0:
            record = parts[1].strip("@") if len(parts) > 1 and parts[1].startswith("@") else ""
        if level <= 1:
            skipping = False
        if level == 1 and len(parts) > 1:
            tag, value = parts[1], parts[2].strip().strip("@") if len(parts) > 2 else ""
            if tag in strip.get(record, ()) or (tag == "CHIL" and value in orphans):
                skipping = True
        if not skipping:
            out.append(line)
    return "".join(out)


# --- scoring ------------------------------------------------------------------------------------------------


@dataclass
class Outcome:
    person: str
    what: str
    verdict: str
    quay: str = "-"
    found: str = ""
    expected: str = ""
    extra: bool = False  # a fact the gold does not have


@dataclass
class Score:
    outcomes: list[Outcome] = field(default_factory=list)
    living: list[str] = field(default_factory=list)

    def _mine(self, links: bool) -> list[Outcome]:
        return [o for o in self.outcomes if (o.what in ("father", "mother")) == links]

    def _rates(self, links: bool) -> tuple[int, int, int, int]:
        count = collections.Counter(o.verdict for o in self._mine(links))
        return count[RIGHT], count[VAGUE], count[WRONG], count[MISSING]

    def precision(self, links: bool = False) -> float | None:
        right, _, wrong, _ = self._rates(links)
        return right / (right + wrong) if right + wrong else None

    def recall(self, links: bool = False) -> float | None:
        gold = [o for o in self._mine(links) if not o.extra]
        return sum(o.verdict == RIGHT for o in gold) / len(gold) if gold else None

    def calibration(self) -> dict[str, tuple[int, int]]:
        """Per QUAY: (held against the gold, scored)."""
        found: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
        for o in self.outcomes:
            if o.verdict in (RIGHT, WRONG):
                found[o.quay][0] += o.verdict == RIGHT
                found[o.quay][1] += 1
        return {q: (a, b) for q, (a, b) in sorted(found.items())}

    def text(self) -> str:
        lines = [
            f"{o.person} {o.what}: {_word(o.verdict)}"
            + (f" ({t('tree')}: {o.found or '-'}; {t('gold')}: {o.expected or '-'})" if o.verdict != RIGHT else "")
            for o in self.outcomes
        ]  # fmt: skip
        lines += [t("living person looked up: {what}", what=w) for w in self.living]
        for links, label in ((False, t("facts")), (True, t("parent links"))):
            right, vague, wrong, missing = self._rates(links)
            lines.append(t(
                "{label}: precision {precision}, recall {recall} ({right} right, {vague} vague, {wrong} wrong, "
                "{missing} missing)",
                label=label, precision=_pct(self.precision(links)), recall=_pct(self.recall(links)),
                right=right, vague=vague, wrong=wrong, missing=missing,
            ))  # fmt: skip
        lines.append(t("held per QUAY: {quays}", quays=", ".join(
            f"{q} {a}/{b}" for q, (a, b) in self.calibration().items()) or "-"))  # fmt: skip
        lines.append(t("lookups of possibly living persons: {n}", n=len(self.living)))
        return "\n".join(lines)

    def json(self) -> str:
        return json.dumps({
            "facts": {"precision": self.precision(), "recall": self.recall()},
            "links": {"precision": self.precision(True), "recall": self.recall(True)},
            "calibration": self.calibration(), "living_lookups": len(self.living),
            "outcomes": [o.__dict__ for o in self.outcomes],
        }, ensure_ascii=False, indent=2)  # fmt: skip


def _word(verdict: str) -> str:
    return {RIGHT: t("right"), VAGUE: t("vague"), WRONG: t("wrong"), MISSING: t("missing")}[verdict]


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def _quay(node) -> str:
    return max((s.value_of("QUAY") for s in node.all("SOUR") if s.value_of("QUAY")), default="-")


def date_verdict(found: str, expected: str) -> str:
    """right: the same date to the gold's precision; vague: consistent but less precise or a range; wrong."""
    if not expected:
        return RIGHT
    if not found:
        return VAGUE
    if " ".join(found.upper().split()) == " ".join(expected.upper().split()):
        return RIGHT
    gold = verify._plain(expected)
    if gold is None:
        # A gold range ("BET 1737 AND 1738"): a date in it is right, a range is vague.
        plain = verify._plain(found)
        if plain is None:
            return VAGUE
        return RIGHT if verify.compare_date(expected, plain) is not False else WRONG
    if plain := verify._plain(found):
        if any(a is not None and b is not None and a != b for a, b in zip(plain, gold, strict=True)):
            return WRONG
        return RIGHT if all(b is None or a is not None for a, b in zip(plain, gold, strict=True)) else VAGUE
    return WRONG if verify.compare_date(found, gold) is False else VAGUE


def _facts(person: GoldPerson, nodes: list) -> list[Outcome]:
    outcomes = []
    for tag in person.tags:
        found = [n for n in nodes if n.tag == tag]
        expected = [f for f in person.facts if f.tag == tag]
        unused = list(found)
        for gold in expected:
            best = None
            for node in unused:
                verdict = date_verdict(node.value_of("DATE"), gold.date)
                if verdict != WRONG and verify.compare_place(node.value_of("PLAC"), gold.place) is False:
                    verdict = WRONG
                rank = (RIGHT, VAGUE, WRONG).index(verdict)
                if best is None or rank < best[0]:
                    best = (rank, verdict, node)
            if best is None:
                outcomes.append(Outcome(person.id, tag, MISSING, expected=_describe(gold.date, gold.place)))
                continue
            _, verdict, node = best
            unused.remove(node)
            outcomes.append(Outcome(
                person.id, tag, verdict, _quay(node), _describe(node.value_of("DATE"), node.value_of("PLAC")),
                _describe(gold.date, gold.place),
            ))  # fmt: skip
        # The gold is complete for its tags: another fact of the tag is a fact the gold refutes.
        for node in unused:
            found_text = _describe(node.value_of("DATE"), node.value_of("PLAC"))
            outcomes.append(Outcome(person.id, tag, WRONG, _quay(node), found_text, extra=True))
    return outcomes


def _describe(date: str, place: str) -> str:
    return ", ".join(x for x in (date, place) if x)


def _parent_matches(person: Person | None, gold: GoldParent) -> bool:
    if person is None:
        return False
    # Without a surname (a patronymic in the given names) name_score cannot reach 2.
    whole = "".join(verify._tokens(person.name)), "".join(verify._tokens(gold.name))
    if verify.name_score(person, gold.name) < 2 and not (not person.surname and verify._similar(*whole)):
        return False
    born = person.birth_date.year if person.birth_date else None
    return gold.born is None or born is None or abs(born - gold.born) <= 2


def _links(person: GoldPerson, tree: Tree, nodes: list) -> list[Outcome]:
    famc = next((n for n in nodes if n.tag == "FAMC"), None)
    quay = _quay(famc) if famc else "-"
    father, mother = tree.parents(person.id)
    outcomes = []
    for gold in person.parents:
        found = father if gold.role == "father" else mother
        if found is None:
            outcomes.append(Outcome(person.id, gold.role, MISSING, expected=gold.name))
            continue
        verdict = RIGHT if _parent_matches(found, gold) else WRONG
        outcomes.append(Outcome(person.id, gold.role, verdict, quay, f"{found.id} {found.name}", gold.name))
    return outcomes


def score(text: str, gold: list[GoldPerson], transcripts: list[Path] = ()) -> Score:
    tree = parse(text)
    nodes = {r.xref: r.children for r in parse_nodes(text, []) if r.tag == "INDI" and r.xref}
    result = Score()
    for person in gold:
        mine = nodes.get(person.id, [])
        result.outcomes += _facts(person, mine) + _links(person, tree, mine)
    result.living = living_lookups(transcripts, tree)
    return result


# --- living persons -----------------------------------------------------------------------------------------


# Local commands (`lineage person`, `ancestors`, the kinship line) may name living persons; what leaves the
# machine may not.
_EXTERNAL = re.compile(r"^\s*(?:lineage\s+(?:archive|rat|scan|htr|forum|mail)\b|curl\b|wget\b)")


def _outgoing(tool: str, data: dict) -> str:
    """The part of a tool call that goes to an outside service."""
    if tool in ("WebSearch", "WebFetch") or tool.startswith("mcp__"):
        return json.dumps(data, ensure_ascii=False)
    if tool == "Bash":
        segments = re.split(r"[;&|\n]+", str(data.get("command", "")))
        return "\n".join(x for x in segments if _EXTERNAL.match(x))
    return ""


def _tool_inputs(path: Path) -> list[tuple[str, str]]:
    found = []
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = entry.get("message")
            if entry.get("type") != "assistant" or not isinstance(message, dict):
                continue
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = block.get("name", "")
                    if outgoing := _outgoing(name, block.get("input") or {}):
                        found.append((name, outgoing))
    return found


def living_lookups(transcripts: list[Path], tree: Tree) -> list[str]:
    """Tool calls in the transcripts that send a possibly living person's name to an outside service."""
    living = [p for p in tree.persons.values() if possibly_living(p, tree)]
    if not living or not transcripts:
        return []
    ids = {p.id for p in living}
    # A name a deceased person also bears says nothing.
    dead = {normalize(p.name) for p in tree.persons.values() if p.id not in ids}
    names = {normalize(p.name): p.id for p in living if len(p.given) >= 3 and p.surname}
    names = {name: pid for name, pid in names.items() if name not in dead}
    found = []
    for path in transcripts:
        for tool, raw in _tool_inputs(path):
            flat = normalize(re.sub(r"\+|%20|_", " ", raw))
            hits = {pid for name, pid in names.items() if name in flat}
            found += [f"{tool} {pid} ({path.name})" for pid in sorted(hits)]
    return found
