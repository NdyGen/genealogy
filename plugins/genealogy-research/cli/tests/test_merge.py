import datetime as dt

import pytest

from lineage.merge import MergeConflict, dedupe_records, mark_researched, resolve_appended_records

SOURCE = b"0 @OA1@ SOUR\r\n1 TITL Marriages Eastbrook\r\n"


def test_identical_duplicate_is_removed_and_first_position_kept():
    data = b"0 HEAD\r\n" + SOURCE + b"0 @I1@ INDI\r\n1 SEX M\r\n" + SOURCE + b"0 TRLR\r\n"
    result, removed = dedupe_records(data)
    assert removed == ["OA1"]
    assert result == b"0 HEAD\r\n" + SOURCE + b"0 @I1@ INDI\r\n1 SEX M\r\n0 TRLR\r\n"


def test_differing_duplicate_is_a_conflict():
    other = b"0 @OA1@ SOUR\r\n1 TITL something else\r\n"
    with pytest.raises(MergeConflict):
        dedupe_records(b"0 HEAD\r\n" + SOURCE + other + b"0 TRLR\r\n")


def test_nothing_to_do_returns_input_unchanged():
    data = b"\xef\xbb\xbf0 HEAD\r\n" + SOURCE + b"0 TRLR\r\n"
    assert dedupe_records(data) == (data, [])


PERSON = b"0 @I1@ INDI\r\n1 NAME John /Miller/\r\n"


def test_research_note_is_appended_to_the_person():
    data = b"\xef\xbb\xbf0 HEAD\r\n" + PERSON + SOURCE + b"0 TRLR\r\n"
    result = mark_researched(data, "I1", dt.date(2026, 9, 30), "reports/persons/I1.md")
    note = b"1 NOTE Deep research 30-09-2026: reports/persons/I1.md\r\n"
    assert result == b"\xef\xbb\xbf0 HEAD\r\n" + PERSON + note + SOURCE + b"0 TRLR\r\n"


def test_second_round_replaces_the_note():
    data = b"0 HEAD\r\n" + PERSON + b"0 TRLR\r\n"
    once = mark_researched(data, "I1", dt.date(2026, 9, 30), "r.md")
    twice = mark_researched(once, "I1", dt.date(2027, 1, 2), "r.md")
    assert twice.count(b"Deep research") == 1 and b"02-01-2027" in twice


def test_research_note_with_continuation_is_replaced_whole():
    long_note = b"1 NOTE Deep research 30-09-2026: r.md\r\n2 CONC  (continued)\r\n"
    data = b"0 HEAD\r\n" + PERSON + long_note + b"1 SEX M\r\n0 TRLR\r\n"
    result = mark_researched(data, "I1", dt.date(2027, 1, 2), "r.md")
    assert b"continued" not in result and b"1 SEX M" in result


def test_findings_note_starting_with_deep_research_is_kept():
    findings = b"1 NOTE Deep research I1 (02-10-2026). Father: John\r\n2 CONC son, according to the record.\r\n"
    data = b"0 HEAD\r\n" + PERSON + findings + b"0 TRLR\r\n"
    result = mark_researched(data, "I1", dt.date(2026, 10, 2), "r.md")
    assert findings in result
    assert result.count(b"1 NOTE Deep research 02-10-2026: r.md\r\n") == 1


def test_unknown_person_is_an_error():
    with pytest.raises(ValueError):
        mark_researched(b"0 HEAD\r\n" + SOURCE + b"0 TRLR\r\n", "OA1", dt.date(2026, 9, 30), "r.md")


def test_duplicate_differing_only_in_other_prefix_is_not_a_conflict():
    clean = b"0 @OA1@ SOUR\r\n1 TITL Court records Northfield\r\n"
    raw = b"0 @OA1@ SOUR\r\n1 TITL other:Court records Northfield\r\n"
    result, removed = dedupe_records(b"0 HEAD\r\n" + clean + raw + b"0 TRLR\r\n")
    assert removed == ["OA1"] and result == b"0 HEAD\r\n" + clean + b"0 TRLR\r\n"


def test_appended_records_on_both_sides_are_both_kept():
    data = (
        b"0 @I1@ INDI\r\n<<<<<<< HEAD\r\n0 @OA2@ SOUR\r\n=======\r\n0 @OA3@ SOUR\r\n>>>>>>> dr/I9\r\n0 TRLR\r\n"
    )
    assert resolve_appended_records(data) == b"0 @I1@ INDI\r\n0 @OA2@ SOUR\r\n0 @OA3@ SOUR\r\n0 TRLR\r\n"


def test_shared_closing_lines_go_to_both_records():
    data = (
        b"<<<<<<< HEAD\r\n0 @OA2@ SOUR\r\n1 TITL Northfield\r\n=======\r\n0 @OA3@ SOUR\r\n1 TITL Eastbrook\r\n"
        b">>>>>>> dr/I9\r\n1 AUTH ACME\r\n1 PUBL Open Archieven\r\n0 TRLR\r\n"
    )
    tail = b"1 AUTH ACME\r\n1 PUBL Open Archieven\r\n"
    assert resolve_appended_records(data) == (
        b"0 @OA2@ SOUR\r\n1 TITL Northfield\r\n" + tail + b"0 @OA3@ SOUR\r\n1 TITL Eastbrook\r\n" + tail + b"0 TRLR\r\n"
    )


def test_conflict_inside_a_record_is_not_resolved():
    data = b"0 @I1@ INDI\r\n<<<<<<< HEAD\r\n1 SEX M\r\n=======\r\n1 SEX F\r\n>>>>>>> dr/I9\r\n0 TRLR\r\n"
    with pytest.raises(MergeConflict):
        resolve_appended_records(data)


def test_request_header_duplicate_subject_and_persons():
    from lineage.merge import merge_request_header

    text = (
        "---\nto: a@b.nl\nsubject: old\nsubject: new\npersons: I1 I2\npersons: I2 I3\n"
        "status: draft\n---\nText\n"
    )
    result, differing = merge_request_header(text)
    assert result == "---\nto: a@b.nl\nsubject: new\npersons: I1 I2 I3\nstatus: draft\n---\nText\n"
    assert differing == []


def test_request_header_other_duplicate_key_is_reported():
    from lineage.merge import merge_request_header

    result, differing = merge_request_header("---\nstatus: draft\nstatus: sent\n---\nx\n")
    assert result == "---\nstatus: sent\n---\nx\n"
    assert differing == ["status"]


def test_request_header_without_duplicates_is_unchanged():
    from lineage.merge import merge_request_header

    text = "---\nto: a\npersons:\nstatus: draft\n---\nText\n---\nmore\n"
    assert merge_request_header(text) == (text, [])
