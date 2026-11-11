"""Mechanical checks of a finished deep-research branch against main, before it is merged.

What a script can decide on its own: which records changed outside the research's reach, which old values
vanished without a trace in a NOTE, where a corrected value still stands elsewhere in the tree, rows taken out
of the coordinate table, the Transkribus count, the account in the report heading and the queue against the
report. Whether a reading is right or a word on the certainty scale fits stays with the reviewing agent.
"""

from __future__ import annotations

import datetime as dt
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from lineage import settings
from lineage.coordinates import TABLE
from lineage.gedcom import parse
from lineage.i18n import t
from lineage.queue import LEGACY_COLUMNS, LIVING_CUTOFF_YEAR, possibly_living

_RECORD = re.compile(r"^0 @([^@]+)@ ")
_POINTER = re.compile(r"@([IF]\d+)@")
_ID = re.compile(r"\b([IF]\d+)\b")
_VALUE_TAGS = ("DATE", "PLAC", "NAME", "GIVN", "SURN")
_DERIVED = re.compile(
    r"identificatie|identiteit|berust|kenmerk|geen andere|identification|identity|rests on|characteristic|no other",
    re.IGNORECASE,
)
# A sentence that anchors the identity in a record naming the parents is not a derived identity.
_PARENTS_NAMED = re.compile(
    r"beide ouders|vader en moeder|ouders genoemd|both parents|father and mother|parents named",
    re.IGNORECASE,
)
_PROVEN = re.compile(r"\b(?:bewezen|proven)\b", re.IGNORECASE)
_NOT_PROVEN = re.compile(r"\bniet bewezen\b|\bnot proven\b|\bonbewezen\b|\bunproven\b", re.IGNORECASE)
_NAMES_RELATION = re.compile(
    r"\bnoem(?:t|en|de|den)\b|verwantschap|\bnames?\b|\bnamed\b|relationship", re.IGNORECASE
)
_QUOTE = re.compile(r'["“„]([^"“”„]{20,})["”]')
_HELPER_READING = re.compile(
    r"alleen door (?:de |een )?hulpagent|lezing (?:van )?(?:de |een )?hulpagent|volgens de hulpagent"
    r"|hulpagent(?:en)?[^.;]{0,40}niet (?:door mij |zelf )?nagelezen"
    r"|only (?:by |read by )?(?:the |a )?helper agent|reading (?:by |of )?(?:the |a )?helper agent"
    r"|according to the helper agent|helper agents?[^.;]{0,40}not (?:re-?read |checked )(?:by me |myself )?",
    re.IGNORECASE,
)
_RESERVATION = re.compile(
    r"onzeker|mogelijk|vermoedelijk|waarschijnlijk|hulpagent|niet zeker|niet nagelezen|lijkt"
    r"|uncertain|possibl[ey]|presum(?:abl[ey]|ed)|probabl[ey]|helper agent|not certain|not re-?read|seems|appears",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“„(])")
_OFF_SCALE = re.compile(
    r"\b(aantoonbaar|vrijwel zeker|bijna zeker|ongetwijfeld|zonder twijfel"
    r"|demonstrabl[ey]|almost certain(?:ly)?|nearly certain|undoubtedly|without (?:a )?doubt)\b",
    re.IGNORECASE,
)
# The scale below "proven": "proven" is left out because a sentence often proves one thing (the parents) and
# grades another (a brother's child), which would give false alarms.
_GRADES = {
    "waarschijnlijk": "probable", "probable": "probable", "probably": "probable",
    "vermoedelijk": "presumed", "presumably": "presumed", "presumed": "presumed",
    "mogelijk": "possible", "possible": "possible", "possibly": "possible",
}  # fmt: skip
_GRADE = re.compile(r"\b(" + "|".join(_GRADES) + r")\b", re.IGNORECASE)
_NOT_A_GRADE = re.compile(
    r"\b(?:niet|zo|waar|indien|zoveel|zo veel) mogelijk\b|\bmogelijk (?:nog )?(?:in )?leven\w*|\bmogelijk levend"
    r"|\b(?:if|where|as \w+ as|not) possible\b|\bpossibly (?:still )?(?:living|alive)",
    re.IGNORECASE,
)
_UNREAD = re.compile(
    r"\bongelezen\b|\bniet (?:gelezen|ingezien|doorzocht|doorgebladerd)\b"
    r"|\bunread\b|\bnot (?:yet )?(?:read|searched|browsed)\b",
    re.IGNORECASE,
)
_SUPERSEDED = re.compile(
    r"achterhaald|superseded|niet online|not online|niet gescand|not scanned|niet gedigitaliseerd|not digiti[sz]ed",
    re.IGNORECASE,
)
_MAX_LINE = 255
_HTR_COUNT = re.compile(
    r"(\d+)\s+(?:Transkribus[- ])?(?:herkenning|recognitions?)"
    r"|(?:herkenningen|recognitions?)\b[^\n\d]{0,40}?(\d+)",
    re.IGNORECASE,
)


@dataclass
class Outcome:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def text(self) -> str:
        lines = [f"ERROR: {m}" for m in self.errors] + [f"WARNING: {m}" for m in self.warnings]
        return "\n".join(lines) if lines else t("no mechanical findings")


def records(text: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.lstrip("\ufeff").replace("\r\n", "\n").split("\n"):
        if m := _RECORD.match(line):
            current = found.setdefault(m.group(1), [])
        elif line.startswith("0 "):
            current = None
            continue
        if current is not None:
            current.append(line)
    return found


def _joined_notes(lines: list[str]) -> str:
    """All NOTE text of a record with CONC/CONT glued back, to search old values in."""
    out, in_note, level = [], False, 0
    for line in lines:
        lvl, _, rest = line.partition(" ")
        tag, _, value = rest.partition(" ")
        if tag == "NOTE":
            in_note, level = True, int(lvl)
            out.append("\n" + value)
        elif in_note and tag in ("CONC", "CONT") and int(lvl) == level + 1:
            out.append(value if tag == "CONC" else "\n" + value)
        else:
            in_note = False
    return "".join(out)


def out_of_reach(old: str, new: str, pid: str, id_block: str) -> list[str]:
    """Changed or removed records the research may not touch: allowed are the person, his families,
    the members of those families and new records in his own ID block."""
    before, after = records(old), records(new)
    tree = parse(new)
    person = tree.persons.get(pid)
    allowed = {pid}
    if person:
        for fid in person.child_of + person.spouse_in:
            allowed.add(fid)
            if fam := tree.families.get(fid):
                allowed.update(fam.partners, fam.children)
    low, _, high = id_block.partition("-")

    def in_block(xref: str) -> bool:
        number = xref[1:]
        return bool(low and number.isdigit() and int(low) <= int(number) <= int(high or low))

    outside = []
    for xref in sorted(set(before) | set(after)):
        if before.get(xref) == after.get(xref) or xref in allowed or in_block(xref):
            continue
        if xref not in before and xref.startswith(("OA", "S")):
            continue
        outside.append(xref)
    return outside


def vanished_values(old: str, new: str) -> list[tuple[str, str]]:
    """Removed DATE/PLAC/NAME values that no NOTE of the record mentions any more: a correction must keep the
    old value ("was ...")."""
    before, after = records(old), records(new)
    found = []
    for xref, lines in before.items():
        if xref not in after or after[xref] == lines:
            continue
        new_set = set(after[xref])
        notes = _joined_notes(after[xref])
        for line in lines:
            if line in new_set:
                continue
            parts = line.split(" ", 2)
            if len(parts) < 3 or parts[1] not in _VALUE_TAGS:
                continue
            # For a name, the given names carry the correction; the surname is often unchanged.
            value = (parts[2].split("/")[0] if parts[1] == "NAME" else parts[2]).strip()
            if value and value not in notes and value not in "\n".join(after[xref]).replace("/", ""):
                found.append((xref, line))
    return found


def vanished_metadata(old: str, new: str) -> list[tuple[str, str]]:
    """Level-1 program tags (_UPD, _UID, ...) dropped from a record that still exists: rewriting a record must
    not lose what the exporting program put there."""
    before, after = records(old), records(new)
    return [(xref, line) for xref, lines in before.items() if xref in after
            for line in lines if line.startswith("1 _") and line not in after[xref]]


def _events(lines: list[str]) -> list[tuple[str, str, str]]:
    """(tag or TYPE, DATE, PLAC) per level-1 event."""
    found, tag, date, plac = [], "", "", ""
    for line in lines + ["1 END"]:
        if line.startswith("1 "):
            if tag and date:
                found.append((tag, date, plac))
            tag, date, plac = line.split(" ")[1], "", ""
        elif line.startswith("2 TYPE "):
            tag = line[7:]
        elif line.startswith("2 DATE "):
            date = line[7:]
        elif line.startswith("2 PLAC "):
            plac = line[7:]
    return found


def old_values_elsewhere(old: str, new: str) -> list[tuple[str, str]]:
    """Events whose date the branch corrected, which other records still carry with the old date (same event
    type and place): the same act copied to a spouse or child, now out of step."""
    before, after = records(old), records(new)
    corrected = set()
    for xref, lines in before.items():
        if xref in after and after[xref] != lines:
            corrected |= set(_events(lines)) - set(_events(after[xref]))
    found = []
    for xref, lines in after.items():
        if before.get(xref) != lines:
            continue
        for ev in set(_events(lines)) & corrected:
            found.append((xref, f"{ev[0]} {ev[1]} {ev[2]}".strip()))
    return sorted(found)


def _famc_blocks(lines: list[str]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in lines:
        if line.startswith("1 FAMC "):
            current = found.setdefault(line[7:].strip("@ "), [])
        elif line.startswith("1 "):
            current = None
        elif current is not None:
            current.append(line)
    return found


def _link_lines(lines: list[str], fam: str) -> list[str]:
    """The person's own NOTEs and the FAMC block of this link: an identification in the NOTE of an
    event (a baptism, a division) reasons about that event, not about the parent link."""
    out: list[str] = []
    keep = False
    for line in lines:
        if line.startswith("1 "):
            keep = line.startswith("1 NOTE") or line == f"1 FAMC @{fam}@"
        if keep:
            out.append(line)
    return out


def _argued_proven(block: list[str]) -> bool:
    """The link's own NOTE opens with "proven" and cites a record naming the relationship, under a source of
    QUAY 2 or 3: the leader made the case A or proven call on purpose and the reviewing agent weighs it. Five
    rounds in a row the warning was a false alarm on exactly such links."""
    note = _joined_notes(block).strip()
    first = _SENTENCE.split(note, 1)[0]
    return (
        any(line in ("3 QUAY 2", "3 QUAY 3") for line in block)
        and bool(_PROVEN.search(first)) and not _NOT_PROVEN.search(first)
        and bool(_NAMES_RELATION.search(note))
    )


def derived_links(old: str, new: str) -> list[tuple[str, str]]:
    """New FAMC links presented as proven (no QUAY 1 under the link) while a NOTE of the child reasons its
    identity from traits: that is case A of a probable link and needs the marking and a decision."""
    before, after = records(old), records(new)
    found = []
    for xref, lines in after.items():
        old_blocks = _famc_blocks(before.get(xref, []))
        for fam, block in _famc_blocks(lines).items():
            if fam in old_blocks or "3 QUAY 1" in block or _argued_proven(block):
                continue
            sentences = _SENTENCE.split(_joined_notes(_link_lines(lines, fam)))
            if any(_DERIVED.search(s) and not _PARENTS_NAMED.search(s) for s in sentences):
                found.append((xref, fam))
    return found


def unsourced_links(old: str, new: str) -> list[tuple[str, str]]:
    """New FAMC links without a SOUR under the link: the record that carries the link then only stands in a
    NOTE, and verify cannot check it (I1171001)."""
    before, after = records(old), records(new)
    found = []
    for xref, lines in after.items():
        old_blocks = _famc_blocks(before.get(xref, []))
        for fam, block in _famc_blocks(lines).items():
            if fam not in old_blocks and not any(line.startswith("2 SOUR") for line in block):
                found.append((xref, fam))
    return found


def unmarked_links(old: str, new: str) -> list[tuple[str, str]]:
    """New FAMC links whose sources are all QUAY 2: neither proven (QUAY 3) nor marked as a probable link
    (QUAY 1 with a decision of the user). I1192001 linked a daughter so, with "QUAY 2" in the report where a
    word of the scale belonged."""
    before, after = records(old), records(new)
    found = []
    for xref, lines in after.items():
        old_blocks = _famc_blocks(before.get(xref, []))
        for fam, block in _famc_blocks(lines).items():
            quays = {line for line in block if line.startswith("3 QUAY ")}
            if fam not in old_blocks and quays == {"3 QUAY 2"}:
                found.append((xref, fam))
    return found


_DMY = re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b")


def future_dates(texts: dict[str, str], today: dt.date) -> list[str]:
    """Dates after today in new text: a reading dated tomorrow (I501817, "12-11-2026" on 11-11) is a typo
    that a reader takes for a later check."""
    found = []
    for where, text in texts.items():
        for m in _DMY.finditer(text):
            try:
                day = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                continue
            if day > today:
                found.append(t("{where}: date {date} lies after today", where=where, date=m.group(0)))
    return found


def _grades(text: str) -> set[str]:
    return {_GRADES[w.lower()] for w in _GRADE.findall(_NOT_A_GRADE.sub(" ", text))}


def _changed_rows(queue_old: str, queue_new: str) -> list[dict[str, str]]:
    def rows(text: str) -> list[dict[str, str]]:
        if not text.strip():
            return []
        header, *lines = text.splitlines()
        columns = [LEGACY_COLUMNS.get(c, c) for c in header.split("\t")]
        return [dict(zip(columns, r.split("\t"), strict=False)) for r in lines if r.strip()]

    old = {r.get("id"): r for r in rows(queue_old)}
    return [r for r in rows(queue_new) if old.get(r.get("id")) != r]


def grade_mismatch(queue_old: str, queue_new: str, texts: dict[str, str]) -> list[str]:
    """A queue reason this round wrote with one word of the scale, while a sentence of the report or a new
    question about the same ID uses another one: the same claim got two grades (wachtrij "mogelijk vader",
    report "vermoedelijk"). Only sentences with a single grade count, so a sentence that grades two
    different claims is left alone."""
    found = []
    for row in _changed_rows(queue_old, queue_new):
        pid, reason = row.get("id", ""), row.get("reason", "")
        if len(grades := _grades(reason)) != 1:
            continue
        mention = re.compile(r"\b" + re.escape(pid) + r"\b")
        for where, text in texts.items():
            for line in text.splitlines():
                for sentence in _SENTENCE.split(line):
                    other = _grades(sentence)
                    if mention.search(sentence) and len(other) == 1 and other != grades:
                        found.append(t(
                            "{pid}: queue reason '{reason}', but {where} says: {sentence}",
                            pid=pid, reason=reason[:80], where=where, sentence=" ".join(sentence.split())[:140],
                        ))
    return found


def skipped_but_old(queue_old: str, queue_new: str, ged_new: str) -> list[str]:
    """Queue items this round skipped as possibly living while the tree at the end of the round dates them long
    ago: `queue add` judged them before the round added a birth bound or the parents' deaths."""
    markers = {"possibly living", t("{reason}; possibly living, do not research", reason="").strip("; ")}
    markers |= {m.split(",")[0] for m in markers}
    tree = parse(ged_new)
    found = []
    for row in _changed_rows(queue_old, queue_new):
        person = tree.persons.get(row.get("id", ""))
        reason = row.get("reason", "")
        if row.get("status") == "skipped" and person and any(m in reason for m in markers) \
                and not possibly_living(person, tree):
            found.append(person.id)
    return found


def _mail_tags(text: str) -> set[str]:
    """Each [mail: ...] question as the text up to its tag, so rewording the question after it is no new one."""
    return {" ".join(m.group(0).split()) for m in re.finditer(r"^.*?\[mail:[^\]]*\]", text, re.MULTILINE)}


def proven_next_to_helper(report: str) -> list[str]:
    """Sentences (or list items) of the report that call something proven and name a helper's reading.
    Per sentence, not per paragraph: a paragraph that proves a link on the lead's own reading and mentions a
    helper only for a negative search or an unlinked sibling gave false alarms."""
    found = []
    for part in re.split(r"\n|(?<=[.;!?])\s+(?=[A-Z*(\"'])", report):
        lowered = re.sub(r"['\"‘“](?:bewezen|proven)['\"’”]", "", part.lower())
        helper = "hulpagent" in lowered or "helper agent" in lowered
        proven = "bewezen" in lowered or "proven" in lowered
        negated = "niet bewezen" in lowered or "not proven" in lowered
        if helper and proven and not negated:
            found.append(part.strip())
    return found


def mail_while_unread(questions_new: str, report_new: str, questions_old: str = "") -> list[str]:
    """Sentences of the report that still call a source unread, in a round that adds a [mail: ...] question:
    a mail only goes out when every other source is exhausted. A source that is not online is no reason to
    wait."""
    if not _mail_tags(questions_new) - _mail_tags(questions_old):
        return []
    found = []
    for line in report_new.splitlines():
        flat = " ".join(line.split())
        if (m := _UNREAD.search(flat)) and not _SUPERSEDED.search(flat):
            found.append(flat[max(0, m.start() - 100):m.end() + 60])
    return found


def _fragments(quote: str) -> list[str]:
    pieces = re.split(r"\s*(?:\[\.\.\.\]|\.\.\.|…)\s*", " ".join(quote.split()).lower())
    return [s for s in pieces if len(s) >= 20]


def helper_quotes(report: str, story: str) -> list[str]:
    """Quotes the report attributes to a helper's reading that the life story repeats without a reservation in
    that sentence or the next."""
    fragments = set()
    for sentence in _SENTENCE.split(report):
        if _HELPER_READING.search(sentence):
            for quote in _QUOTE.findall(sentence):
                fragments.update(_fragments(quote))
    sentences = _SENTENCE.split(story)
    found = []
    for i, sentence in enumerate(sentences):
        flat = " ".join(sentence.split()).lower()
        if any(f in flat for f in fragments) and not _RESERVATION.search(" ".join(sentences[i:i + 2])):
            found.append(" ".join(sentence.split())[:160])
    return found


_PROVEN_ON_DERIVED = re.compile(
    r"\b(?:bewezen|proven)\s+(?:op|uit|volgens|on|from|by)\s+(?:het|de|een|the|an?)\s+"
    r"(?:regest(?:en)?|index|catalogus(?:titel)?|catalogue(?: title)?|inventaris(?:beschrijving)?|abstract)\b",
    re.IGNORECASE,
)
# An enumerated feature "(2) residence ..." whose head word belongs to the name: name, patronymic and place.
_NAME_ITEM = re.compile(
    r"\(\s*(?:\d|i{1,3}|[a-c])\s*\)\s*(?:de |het |zijn |haar |the |his |her )?"
    r"(?:naam|namen|patroniem|achternaam|familienaam|woonplaats|plaats|name|patronymic|surname|residence|place)\b"
    r"(?! van (?:zijn|haar|de|het) | of (?:his|her|the) | onder | among )",
    re.IGNORECASE,
)


_ONE_FEATURE = re.compile(r"(?:één|een|one|single) kenmerk|one feature|samen één|together one", re.IGNORECASE)


def proven_on_derived(texts: dict[str, str]) -> list[str]:
    """'Proven on the regest/index': a derived source is never the record of 'proven'."""
    found = []
    for where, text in texts.items():
        for sentence in _SENTENCE.split(text):
            if _PROVEN_ON_DERIVED.search(sentence) and not _NOT_PROVEN.search(sentence):
                found.append(t(
                    "{where}: 'proven' on a derived source (regest, index, catalogue): {sentence}",
                    where=where,
                    sentence=" ".join(sentence.split())[:140],
                ))
    return found


def name_counted_twice(texts: dict[str, str]) -> list[str]:
    """Name, patronymic and place are one feature; reviews kept finding them counted as (1) and (2)."""
    found = []
    for where, text in texts.items():
        for sentence in (s for line in text.splitlines() for s in _SENTENCE.split(line)):
            if len(_NAME_ITEM.findall(sentence)) >= 2 and not _ONE_FEATURE.search(sentence):
                found.append(t(
                    "{where}: place, patronymic or surname counted as a separate feature "
                    "(name, patronymic and place are one): {sentence}",
                    where=where,
                    sentence=" ".join(sentence.split())[:140],
                ))
    return found


def off_scale(texts: dict[str, str]) -> list[str]:
    """Certainty words that are not on the scale; reviews kept finding 'aantoonbaar' in five rounds out of six."""
    found = []
    for where, text in texts.items():
        for sentence in _SENTENCE.split(text):
            if m := _OFF_SCALE.search(sentence):
                found.append(t(
                        "{where}: '{word}' is not on the certainty scale: {sentence}",
                        where=where,
                        word=m.group(1),
                        sentence=" ".join(sentence.split())[:140],
                    ))
    return found


_OWN_EVENTS = ("BIRT", "CHR", "BAPM")
_WRONG_PRONOUN = {
    "F": re.compile(r"\b(?:Zijn|His)\s+(?:moeder|vader|ouders|mother|father|parents)\b"),
    "M": re.compile(r"\b(?:Haar|Her)\s+(?:moeder|vader|ouders|mother|father|parents)\b"),
}


def _own_event_notes(lines: list[str]) -> str:
    """NOTE text under the record's own birth and baptism, where the parents named are the person's."""
    out, event = [], ""
    for line in lines:
        if line.startswith("1 "):
            event = line.split(" ")[1]
        elif event in _OWN_EVENTS:
            out.append(line)
    return _joined_notes(out)


def pronoun_mismatch(old: str, new: str) -> list[tuple[str, str]]:
    """A NOTE copied from a brother kept "Zijn moeder" at his sister."""
    before = records(old)
    found = []
    for xref, lines in records(new).items():
        sex = next((line[6:].strip() for line in lines if line.startswith("1 SEX ")), "")
        if sex not in _WRONG_PRONOUN:
            continue
        old_text = _own_event_notes(before.get(xref, []))
        for m in _WRONG_PRONOUN[sex].finditer(_own_event_notes(lines)):
            if m.group(0) not in old_text:
                found.append((xref, m.group(0)))
    return found


def new_lines(old: str, new: str) -> list[str]:
    existing = set(old.splitlines())
    return [r for r in new.splitlines() if r not in existing]


def long_lines(old: str, new: str) -> list[str]:
    return [r for r in new_lines(old, new) if len(r) > _MAX_LINE]


def removed_rows(old: str, new: str) -> list[str]:
    after = set(new.splitlines())
    # The header line is skipped: the table's column names were translated.
    return [r for r in old.splitlines()[1:] if r.strip() and r not in after]


def new_queue_ids(old: str, new: str) -> set[str]:
    def ids(text: str) -> set[str]:
        return {r.split("\t", 1)[0] for r in text.splitlines()[1:] if r.strip()}
    return ids(new) - ids(old)


def id_block(queue_text: str, pid: str) -> str:
    header, *rows = queue_text.splitlines()
    columns = [LEGACY_COLUMNS.get(c, c) for c in header.split("\t")]
    for row in rows:
        values = dict(zip(columns, row.split("\t"), strict=False))
        if values.get("id") == pid:
            return values.get("id_block", "")
    return ""


def htr_count(log: str, pid: str, since: dt.datetime) -> int:
    count = 0
    for line in log.splitlines():
        stamp, _, rest = line.partition("\t")
        try:
            moment = dt.datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if moment >= since and f"dr-{pid}/" in rest:
            count += 1
    return count


def check(
    pid: str,
    ged_old: str,
    ged_new: str,
    queue_old: str,
    queue_new: str,
    coords_old: str,
    coords_new: str,
    report_new: str,
    account: str,
    htr: int,
    report_full: str = "",
    story: str = "",
    questions_new: str = "",
    questions_old: str = "",
    today: dt.date | None = None,
) -> Outcome:
    """`report_new` is only the text this branch added to the report, `report_full` the whole report,
    `questions_new` the lines it added to the open questions, `questions_old` those questions before."""
    u = Outcome()
    for row in removed_rows(coords_old, coords_new):
        u.errors.append(t("coordinate table: row removed or changed (only adding is allowed): {row}", row=row[:120]))
    numbers = {int(next(g for g in groups if g)) for groups in _HTR_COUNT.findall(report_new)}
    if htr not in numbers:
        reported = ", ".join(map(str, sorted(numbers))) or t("none")
        u.errors.append(t(
            "Transkribus: {count} recognitions in the log for dr-{pid}, the report mentions {reported}",
            count=htr,
            pid=pid,
            reported=reported,
        ))
    if account and account not in report_new:
        u.errors.append(t(
                "the report does not mention the account '{account}' (output/account) in the new text",
                account=account,
            ))
    added = new_queue_ids(queue_old, queue_new)
    mentioned = set(_ID.findall(report_new))
    for x in sorted(added - mentioned):
        u.errors.append(t("queue: {pid} added, but the report does not mention it", pid=x))
    block = id_block(queue_new, pid)
    for x in out_of_reach(ged_old, ged_new, pid, block):
        u.warnings.append(t("{xref} changed outside the reach of {pid}: does the report explain that?", xref=x, pid=pid))
    for x, line in vanished_values(ged_old, ged_new):
        u.warnings.append(t("{xref}: '{line}' vanished without a NOTE naming the old value", xref=x, line=line))
    for x, line in vanished_metadata(ged_old, ged_new):
        u.warnings.append(t("{xref}: program line '{line}' removed", xref=x, line=line))
    for x, ev in old_values_elsewhere(ged_old, ged_new):
        u.warnings.append(t("{xref} still has '{event}', a value this round corrected elsewhere", xref=x, event=ev))
    for x in skipped_but_old(queue_old, queue_new, ged_new):
        u.warnings.append(t(
            "queue: {pid} skipped as possibly living, but the tree now dates him or her before {year}: set to open?",
            pid=x, year=LIVING_CUTOFF_YEAR,
        ))
    u.warnings.extend(grade_mismatch(
        queue_old, queue_new, {t("report"): report_new, t("open questions"): questions_new},
    ))
    for sentence in mail_while_unread(questions_new, report_new, questions_old)[:3]:
        u.warnings.append(t(
            "open questions: a new [mail: ...] question, while the report still calls a source unread: {sentence}",
            sentence=sentence,
        ))
    for sentence in proven_next_to_helper(report_new):
        u.warnings.append(t("report: 'proven' next to a helper agent's reading: {paragraph}", paragraph=sentence[:160]))
    for x, fam in derived_links(ged_old, ged_new):
        u.warnings.append(
            t(
                "{xref}: new FAMC @{fam}@ without QUAY 1, while a NOTE derives the identity: "
                "proven, or probable (case A, mark it and ask the user)?",
                xref=x,
                fam=fam,
            )
        )
    for x, fam in unsourced_links(ged_old, ged_new):
        u.warnings.append(t("{xref}: new FAMC @{fam}@ without a SOUR under the link", xref=x, fam=fam))
    for x, fam in unmarked_links(ged_old, ged_new):
        u.warnings.append(t(
            "{xref}: new FAMC @{fam}@ with only QUAY 2 sources: proven (QUAY 3) or probable "
            "(case A: QUAY 1 and a decision of the user)?",
            xref=x, fam=fam,
        ))
    for x, words in pronoun_mismatch(ged_old, ged_new):
        u.warnings.append(t("{xref}: '{words}' in a birth or baptism NOTE does not match the sex", xref=x, words=words))
    for line in long_lines(ged_old, ged_new):
        u.errors.append(t(
                "GEDCOM: new line of {length} characters (max {max}, split with CONC): {line}",
                length=len(line),
                max=_MAX_LINE,
                line=line[:80],
            ))
    new_notes = "\n".join(r.split(" ", 2)[2] for r in new_lines(ged_old, ged_new)
                          if r.split(" ", 2)[1:2] in (["NOTE"], ["CONC"], ["CONT"]) and r.count(" ") >= 2)
    u.warnings.extend(off_scale({t("report"): report_new, "GEDCOM": new_notes}))
    u.warnings.extend(proven_on_derived({t("report"): report_new, "GEDCOM": new_notes, t("life story"): story}))
    u.warnings.extend(name_counted_twice({t("report"): report_new, "GEDCOM": new_notes}))
    u.warnings.extend(future_dates(
        {t("report"): report_new, "GEDCOM": new_notes, t("open questions"): questions_new}, today or dt.date.today(),
    ))
    u.warnings.extend(_story_warnings(report_full, story))
    return u


def _story_warnings(report: str, story: str) -> list[str]:
    return [
        t("life story: quote from a helper agent's reading without reservation: {quote}", quote=z)
        for z in helper_quotes(report, story)
    ] + off_scale({t("life story"): story})


def _git(root: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""


def _show(root: Path, ref: str, *paths: str) -> str:
    for path in paths:
        if text := _git(root, "show", f"{ref}:{path}"):
            return text
    return ""


def _marker(directory: Path, *names: str) -> Path | None:
    return next((p for n in names if (p := directory / n).exists()), None)


def review_branch(root: Path, pid: str) -> Outcome:
    branch = f"dr/{pid}"
    base = _git(root, "merge-base", "main", branch).strip()
    if not base:
        raise ValueError(t("branch {branch} not found", branch=branch))
    project = settings.current()
    report = f"{project.rel('person_reports').as_posix()}/{pid}.md"

    def added_lines(path: str) -> str:
        return "\n".join(
            r[1:]
            for r in _git(root, "diff", f"{base}..{branch}", "--", path).splitlines()
            if r.startswith("+") and not r.startswith("+++")
        )

    added = added_lines(report)
    questions = added_lines(project.rel("questions").as_posix())
    common = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    wt = common.parent / ".worktrees" / f"dr-{pid}"
    report_full = _show(root, branch, report)
    story = _show(root, branch, f"{project.rel('life_stories').as_posix()}/{pid}.md")
    out = wt / project.rel("output")
    if _marker(out, "update", "stale", "bijwerk"):
        return Outcome(warnings=_story_warnings(report_full, story))
    account_file = out / "account"
    account = account_file.read_text().strip() if account_file.exists() else ""
    since = dt.datetime.fromtimestamp(int(_git(root, "log", "-1", "--format=%ct", base).strip()))
    log = next((p for n in ("lineage-htr.log", "ndygen-htr.log") if (p := common / n).exists()), None)
    htr = htr_count(log.read_text(encoding="utf-8") if log else "", pid, since)

    gedcom = project.rel("gedcom")
    queue = project.rel("queue").as_posix()
    # Dutch-named coordinates next to the tree, as coordinates.table_for, for a branch from before the rename.
    coordinates = [(gedcom.parent / name).as_posix() for name in (TABLE.name, "coordinaten.tsv")]

    def show(ref: str, *paths: str) -> str:
        return _show(root, ref, *paths)

    return check(
        pid,
        show(base, gedcom.as_posix()), show(branch, gedcom.as_posix()),
        show(base, queue), show(branch, queue),
        show(base, *coordinates), show(branch, *coordinates),
        added, account, htr, report_full, story, questions, show(base, project.rel("questions").as_posix()),
    )
