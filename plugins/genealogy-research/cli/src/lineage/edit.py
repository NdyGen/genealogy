"""Writing to data/tree.ged without a full round trip through the parser: the file is edited as a
list of lines, so everything that is not touched stays byte for byte the same (BOM, CRLF, MyHeritage tags).
"""

from __future__ import annotations

from pathlib import Path

from lineage.i18n import t

WIDTH = 200


class EditError(ValueError):
    pass


def read(path: Path) -> list[str]:
    return path.read_bytes().decode("utf-8").split("\r\n")


def write(path: Path, lines: list[str]) -> None:
    path.write_bytes("\r\n".join(lines).encode("utf-8"))


def line_level(line: str) -> int:
    return int(line.split(" ", 1)[0])


def record(lines: list[str], xref: str) -> int:
    """Index of the level-0 line of record @xref@."""
    header = f"0 @{xref.strip('@')}@ "
    for i, line in enumerate(lines):
        if line.lstrip("﻿").startswith(header):
            return i
    raise EditError(t("record @{xref}@ not found", xref=xref.strip("@")))


def block_end(lines: list[str], start: int) -> int:
    """Index just after the structure that starts at `start` (the line itself plus all deeper lines)."""
    own = line_level(lines[start])
    i = start + 1
    while i < len(lines) and lines[i] and line_level(lines[i]) > own:
        i += 1
    return i


def find(lines: list[str], start: int, line: str) -> int:
    """Index of the first line equal to `line` inside the structure that starts at `start`."""
    for i in range(start + 1, block_end(lines, start)):
        if lines[i] == line:
            return i
    raise EditError(t("{line!r} not found in {parent!r}", line=line, parent=lines[start]))


def text(level: int, tag: str, value: str, width: int = WIDTH) -> list[str]:
    """A tag with a long value: newlines become CONT, long lines CONC.

    A CONC split never falls next to a space, because readers that trim values would lose it.
    """
    out: list[str] = []
    for n, paragraph in enumerate(value.split("\n")):
        header = f"{level} {tag}" if n == 0 else f"{level + 1} CONT"
        pieces = _split(paragraph, width) or [""]
        out.append(f"{header} {pieces[0]}".rstrip())
        out.extend(f"{level + 1} CONC {piece}" for piece in pieces[1:])
    return out


def _split(value: str, width: int) -> list[str]:
    pieces = []
    while len(value) > width:
        cut = width
        while cut > 1 and (value[cut - 1] == " " or value[cut] == " "):
            cut -= 1
        if cut == 1:
            raise EditError(t("no split point without a space found"))
        pieces.append(value[:cut])
        value = value[cut:]
    if value:
        pieces.append(value)
    return pieces


def source(
    level: int,
    source_id: str,
    page: str,
    quality: int | None = None,
    note: str | None = None,
) -> list[str]:
    """A citation: SOUR with PAGE and QUAY one level deeper, and an optional NOTE beside it (same level as SOUR)."""
    out = [f"{level} SOUR @{source_id.strip('@')}@", *text(level + 1, "PAGE", page)]
    if quality is not None:
        if quality not in range(4):
            raise EditError(t("QUAY {quality} does not exist (0-3)", quality=quality))
        out.append(f"{level + 1} QUAY {quality}")
    if note:
        out += text(level, "NOTE", note)
    return out


def insert(lines: list[str], index: int, new: list[str]) -> None:
    lines[index:index] = new
