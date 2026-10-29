"""Byte-level edits after merging research branches: dedupe records, mark researched persons.

Works on bytes so BOM, CRLF and untouched records stay exactly as they were.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from lineage.i18n import t

_RECORD_START = re.compile(rb"^0 @([^@]+)@ ")
# Exact marker format: leaders also write findings notes that start with "Deep research <ID> (...)".
RESEARCH_NOTE = re.compile(rb"^1 NOTE Deep research \d{2}-\d{2}-\d{4}: ")


class MergeConflict(ValueError):
    pass


def _records(data: bytes) -> list[tuple[str | None, bytes]]:
    records: list[tuple[str | None, bytes]] = []
    current: list[bytes] = []
    xref: str | None = None
    for line in data.splitlines(keepends=True):
        if line.startswith(b"0 "):
            if current:
                records.append((xref, b"".join(current)))
            match = _RECORD_START.match(line)
            xref = match[1].decode() if match else None
            current = [line]
        else:
            current.append(line)
    if current:
        records.append((xref, b"".join(current)))
    return records


def _comparable(body: bytes) -> bytes:
    """Older source records kept Open Archieven's "other:" in their title; a cleaned copy is the same record."""
    return body.replace(b"\n1 TITL other:", b"\n1 TITL ")


def dedupe_records(data: bytes) -> tuple[bytes, list[str]]:
    """Keep the first of identical records sharing an ID; differing ones are a real conflict."""
    seen: dict[str, bytes] = {}
    kept: list[bytes] = []
    removed: list[str] = []
    for xref, body in _records(data):
        if xref is None:
            kept.append(body)
            continue
        if xref in seen:
            if _comparable(seen[xref]) != _comparable(body):
                raise MergeConflict(
                    t("ID {xref} occurs twice in the file with different content", xref=xref)
                )
            removed.append(xref)
            continue
        seen[xref] = body
        kept.append(body)
    return b"".join(kept), removed


def dedupe_file(path: Path) -> list[str]:
    data, removed = dedupe_records(path.read_bytes())
    if removed:
        path.write_bytes(data)
    return removed


# Lines after the hunk up to the next record are shared by both sides' last record: git prints them once.
_APPEND_HUNK = re.compile(
    rb"^<<<<<<< [^\n]*\n(.*?)^=======\r?\n(.*?)^>>>>>>> [^\n]*\n((?:(?!0 |<<<<<<< )[^\n]*\n)*)",
    re.S | re.M,
)


def resolve_appended_records(data: bytes) -> bytes:
    """Resolve conflicts where both branches appended different whole records at the same spot: keep both."""

    def keep_both(m: re.Match[bytes]) -> bytes:
        ours, theirs, tail = m.group(1), m.group(2), m.group(3)
        for side in (ours, theirs):
            if side and not side.startswith(b"0 @"):
                raise MergeConflict(t("conflict in the middle of a record"))
        if not tail:
            return ours + theirs
        if not (ours and theirs):
            raise MergeConflict(t("conflict with shared closing lines but one empty side"))
        return ours + tail + theirs + tail

    return _APPEND_HUNK.sub(keep_both, data)


def resolve_appended_file(path: Path) -> None:
    path.write_bytes(resolve_appended_records(path.read_bytes()))


def mark_researched(data: bytes, pid: str, date: dt.date, report: str) -> bytes:
    """Replaces an earlier research note, so the person shows only the latest round."""
    out: list[bytes] = []
    found = False
    for xref, body in _records(data):
        if xref == pid and body.split(b" ", 2)[2].startswith(b"INDI"):
            lines = body.splitlines(keepends=True)
            eol = b"\r\n" if lines[0].endswith(b"\r\n") else b"\n"
            kept: list[bytes] = []
            in_note = False
            for line in lines:
                if RESEARCH_NOTE.match(line):
                    in_note = True
                elif not (in_note and line.startswith((b"2 CONC", b"2 CONT"))):
                    in_note = False
                    kept.append(line)
            note = f"Deep research {date:%d-%m-%Y}: {report}".encode()
            body = b"".join(kept) + b"1 NOTE " + note + eol
            found = True
        out.append(body)
    if not found:
        raise ValueError(t("person {pid} is not in the file", pid=pid))
    return b"".join(out)


def mark_researched_file(path: Path, pid: str, date: dt.date, report: str) -> None:
    path.write_bytes(mark_researched(path.read_bytes(), pid, date, report))


PERSONS_KEYS = ("persons", "personen")
SUBJECT_KEYS = ("subject", "onderwerp")


def merge_request_header(text: str) -> tuple[str, list[str]]:
    """Merge duplicate keys in the header of a request.

    After a union merge the branch's value comes last. `persons` becomes the union, the other keys
    get the last value. Returns the text and the keys (except the subject and persons) that had
    different values. The Dutch keys `personen` and `onderwerp` are still accepted."""
    if not text.startswith("---\n"):
        return text, []
    header, separator, rest = text[4:].partition("\n---\n")
    if not separator:
        return text, []
    lines = header.split("\n")
    values: dict[str, list[str]] = {}
    for line in lines:
        key = line.partition(":")[0].strip()
        if key and ":" in line:
            values.setdefault(key, []).append(line.partition(":")[2].strip())
    duplicated = {k for k, v in values.items() if len(v) > 1}
    if not duplicated:
        return text, []
    new: list[str] = []
    done: set[str] = set()
    differing: list[str] = []
    for line in lines:
        key = line.partition(":")[0].strip()
        if key not in duplicated or ":" not in line:
            new.append(line)
            continue
        if key in done:
            continue
        done.add(key)
        v = values[key]
        if key in PERSONS_KEYS:
            ids = list(dict.fromkeys(i for item in v for i in item.replace(",", " ").split()))
            new.append(f"{key}: " + " ".join(ids))
            continue
        new.append(f"{key}: {v[-1]}")
        if key not in SUBJECT_KEYS and len(set(v)) > 1:
            differing.append(key)
    return "---\n" + "\n".join(new) + separator + rest, differing


def merge_request_header_file(path: Path) -> list[str] | None:
    """Rewrites the header if it had duplicate keys; then returns the keys that differed, otherwise None."""
    text = path.read_text(encoding="utf-8")
    new, differing = merge_request_header(text)
    if new == text:
        return None
    path.write_text(new, encoding="utf-8", newline="")
    return differing
