import pytest

from lineage.gedcom import GedcomError, parse, parse_nodes
from tests.conftest import ged


def test_persons_families_and_sources(tree):
    assert len(tree.persons) == 7
    assert len(tree.families) == 3
    assert tree.sources["S1"].title == "Civil Registry Northfield, births"


def test_name_split_on_slashes(tree):
    person = tree.persons["I1"]
    assert (person.given, person.surname, person.name) == ("John", "Miller", "John Miller")


def test_events_and_citations(tree):
    birth = tree.persons["I1"].event("BIRT")
    assert birth.place == "Northfield"
    assert birth.date.year == 1920
    assert birth.citations[0].source_id == "S1"
    assert birth.citations[0].page == "record 123"
    assert tree.persons["I2"].event("OCCU").value == "Carpenter"


def test_parents_and_children(tree):
    father, mother = tree.parents("I1")
    assert (father.id, mother.id) == ("I2", "I3")
    assert [c.id for c in tree.children(tree.families["F3"])] == ["I7"]


def test_conc_and_cont_are_joined():
    tree = parse(ged("0 @I1@ INDI", "1 NOTE First", "2 CONC  part", "2 CONT second line"))
    assert tree.persons["I1"].notes == ["First part\nsecond line"]


def test_note_records_are_resolved():
    tree = parse(ged("0 @I1@ INDI", "1 NOTE @N1@", "0 @N1@ NOTE From the record"))
    assert tree.persons["I1"].notes == ["From the record"]


def test_utf8_character_split_across_conc_is_repaired():
    raw = b"0 HEAD\r\n0 @I1@ INDI\r\n1 NOTE Caf\xc3\r\n2 CONC \xa9 au lait\r\n0 TRLR\r\n"
    tree = parse(raw.decode("utf-8", "surrogateescape"))
    assert tree.persons["I1"].notes == ["Café au lait"]


def test_stray_line_is_kept_and_reported():
    tree = parse(ged("0 @I1@ INDI", "1 NOTE Age Francis: 29", "Age Joanna: 24"))
    assert tree.persons["I1"].notes == ["Age Francis: 29\nAge Joanna: 24"]
    assert len(tree.format_problems) == 1


def test_strict_parsing_rejects_level_jump():
    with pytest.raises(GedcomError):
        parse_nodes("0 HEAD\n2 VERS 5.5.1")


def test_only_real_line_breaks_split_lines():
    tree = parse(ged("0 @I1@ INDI", "1 NOTE a b"))
    assert tree.persons["I1"].notes == ["a b"]
