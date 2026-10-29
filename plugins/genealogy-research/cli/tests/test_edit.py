import pytest

from lineage import edit
from lineage.gedcom import parse_nodes

LINES = [
    "﻿0 HEAD",
    "0 @I1@ INDI",
    "1 NAME John /Smith/",
    "1 BIRT",
    "2 DATE 1 JAN 1800",
    "2 SOUR @S1@",
    "3 PAGE record 1",
    "1 DEAT Y",
    "0 @S1@ SOUR",
    "1 TITL BS",
    "0 TRLR",
]


def test_record_and_block_end():
    i = edit.record(LINES, "I1")
    assert i == 1
    birt = edit.find(LINES, i, "1 BIRT")
    assert edit.block_end(LINES, birt) == 7
    assert edit.block_end(LINES, i) == 8


def test_record_in_first_line_after_bom():
    assert edit.record(["﻿0 @I9@ INDI", "0 TRLR"], "@I9@") == 0


def test_missing_record_raises():
    with pytest.raises(edit.EditError):
        edit.record(LINES, "I404")


def test_long_text_never_splits_next_to_a_space_and_round_trips():
    value = ("word " * 80).strip() + "\nsecond line"
    lines = edit.text(2, "NOTE", value, width=30)
    assert all(len(r) < 40 for r in lines)
    for r in lines:
        if " CONC " in r:
            piece = r.split(" CONC ", 1)[1]
            assert not piece.startswith(" ")
    previous = [r for r in lines if " CONC " not in r and " CONT " not in r][0]
    assert not previous.endswith(" ")
    text = "\r\n".join(["0 @I1@ INDI", "1 BIRT", *lines, "0 TRLR"])
    assert parse_nodes(text)[0].children[0].children[0].value == value


def test_citation_with_quality_and_note():
    lines = edit.source(2, "@S5@", "record 2", 3, "source text")
    assert lines == ["2 SOUR @S5@", "3 PAGE record 2", "3 QUAY 3", "2 NOTE source text"]


def test_unknown_quality_is_refused():
    with pytest.raises(edit.EditError):
        edit.source(2, "S5", "record 2", 4)


def test_file_round_trip_keeps_bom_and_crlf(tmp_path):
    path = tmp_path / "t.ged"
    path.write_bytes("\r\n".join(LINES).encode("utf-8"))
    lines = edit.read(path)
    edit.insert(lines, edit.block_end(lines, 3), edit.source(2, "S1", "record 9", 2))
    edit.write(path, lines)
    data = path.read_bytes()
    assert (
        data.startswith("﻿".encode())
        and b"\r\n2 SOUR @S1@\r\n3 PAGE record 9\r\n3 QUAY 2\r\n1 DEAT Y" in data
    )
