from pathlib import Path

import pytest

from lineage import archive, settings, verify
from lineage.archive import Record, RecordPerson
from tests.conftest import ged

OA = "https://www.openarchieven.nl/abc:11111111-2222-3333-4444-555555555555"
REF = "abc:11111111-2222-3333-4444-555555555555"


def _person(xref: str, name: str, *lines: str) -> str:
    return "\n".join([f"0 @{xref}@ INDI", f"1 NAME {name}", *lines])


def _cite(page: str = OA, quay: str = "3", level: int = 2) -> str:
    return "\n".join([f"{level} SOUR @S1@", f"{level + 1} PAGE {page}", f"{level + 1} QUAY {quay}"])


def _record(event: str, date: tuple, place: str, *persons: tuple[str, str]) -> Record:
    return Record(
        archive="abc", identifier="x", source_type="DTB", event=event, date="", place=place, institution="",
        date_parts=date, persons=[RecordPerson(role=role, name=name) for role, name in persons],
    )  # fmt: skip


@pytest.fixture
def records(monkeypatch):
    found: dict[str, Record] = {}

    def show(ref, offline=False):
        if ref not in found:
            raise archive.RecordNotFound(f"record {ref} not found")
        return found[ref]

    monkeypatch.setattr(archive, "show", show)
    return found


@pytest.mark.parametrize(
    "page, kind, ref",
    [
        (f"akte 12, 1-2-1850; {OA}", "oa", REF),
        ("Krant 3-3-1906; https://resolver.kb.nl/resolve?urn=ddd:010188815:mpeg21:a0018", "delpher",
         "ddd:010188815:mpeg21:a0018"),
        ("RAT 929 (Schepenbank) inv. 145 p. 251-255 (scans 0255-0259), deling 1742", "scan", "rat:929-145/0255"),
        ("protocol fol. 3; scan: output/scans/akte-3.jpg", "scan", "scan: output/scans/akte-3.jpg"),
        ("Bidprentje; https://example.org/bid/7", "url", "https://example.org/bid/7"),
        ("Genealogie, p. 12", "", ""),
        ("inv. 145, fol. 12r-13v, scans 0255-0256, 3-4-1742 (scan gelezen)", "scan", "S1:145/0255-0256"),
        ("fol. 248v-249, contract 17-2-1728, scans 254-255", "scan", "S1:/254-255"),
    ],
)  # fmt: skip
def test_reference_forms(page, kind, ref):
    assert verify.reference(verify.Citation("S1", page, "3", "")) == (kind, ref)


def test_only_new_or_changed_facts_are_checked():
    old = ged(_person("I1", "Jan /Dekkers/", "1 BIRT", "2 DATE 1 FEB 1850", _cite()))
    new = ged(
        _person("I1", "Jan /Dekkers/", "1 BIRT", "2 DATE 1 FEB 1850", _cite(), "1 DEAT", "2 DATE 1900", _cite()),
    )
    assert [f.tag for f in verify.changed_facts(old, new)] == ["DEAT"]


def test_same_event_with_matching_date_and_latin_name_is_supported(records):
    records[REF] = _record("Geboorte", (1, 2, 1850), "Breda", ("Kind", "Joannes Dekkers"))
    new = ged(_person("I1", "Jan /Dekkers/", "1 BIRT", "2 DATE 1 FEB 1850", "2 PLAC Breda", _cite()))
    result = verify.verify("", new)
    assert result.counts()[verify.SUPPORTED] == 1
    assert not result.errors and not result.warnings


def test_contradicted_date_on_proven_fact_is_an_error(records):
    records[REF] = _record("Geboorte", (1, 2, 1851), "Breda", ("Kind", "Jan Dekkers"))
    result = verify.verify("", ged(_person("I1", "Jan /Dekkers/", "1 BIRT", "2 DATE 1 FEB 1850", _cite())))
    assert result.counts()[verify.CONTRADICTED] == 1
    assert "1 FEB 1850" in result.errors[0] and "1-2-1851" in result.errors[0]


def test_contradiction_on_lower_quay_is_a_warning(records):
    records[REF] = _record("Geboorte", (1, 2, 1851), "Breda", ("Kind", "Jan Dekkers"))
    result = verify.verify("", ged(_person("I1", "Jan /Dekkers/", "1 BIRT", "2 DATE 1 FEB 1850", _cite(quay="2"))))
    assert not result.errors and len(result.warnings) == 1


def test_burial_a_few_days_off_is_partly_supported(records):
    records[REF] = _record("Begraven", (11, 5, 1781), "Breda", ("Overledene", "Jan Dekkers"))
    result = verify.verify("", ged(_person("I1", "Jan /Dekkers/", "1 BURI", "2 DATE 14 MAY 1781", _cite())))
    assert result.counts()[verify.PARTIAL] == 1
    assert not result.errors


def test_marriage_indexed_at_the_banns_is_partly_supported(records):
    records[REF] = _record("Huwelijk", (16, 5, 1783), "Breda", ("Bruidegom", "Jan Dekkers"), ("Bruid", "Kee Smit"))
    new = ged(_person("I1", "Jan /Dekkers/", "1 FAMS @F1@"), _person("I2", "Kee /Smit/", "1 FAMS @F1@"),
              "0 @F1@ FAM\n1 HUSB @I1@\n1 WIFE @I2@\n1 MARR\n2 DATE 1 JUN 1783\n" + _cite())
    result = verify.verify("", new)
    assert result.counts()[verify.PARTIAL] == 1 and not result.errors


def test_a_mother_is_not_taken_for_her_child(records):
    records[REF] = _record("Geboorte", (31, 12, 1834), "Zutphen", ("Kind", "Hendrik Dekkers"),
                           ("Vader", "Piet Dekkers"), ("Moeder", "Kee Smit"))  # fmt: skip
    result = verify.verify("", ged(_person("I1", "Kee /Dekkers/", "1 BIRT", "2 DATE ABT 1809", _cite())))
    assert result.counts()[verify.CONTRADICTED] == 0 and not result.errors


def test_a_remarriage_naming_the_first_husband_does_not_date_the_first_marriage(records):
    records[REF] = _record("Huwelijk", (8, 12, 1816), "Drunen", ("Bruidegom", "Piet Smit"), ("Bruid", "Kee Smit"),
                           ("other:Eerdere man", "Jan Dekkers"))  # fmt: skip
    new = ged(_person("I1", "Jan /Dekkers/", "1 FAMS @F1@"), _person("I2", "Kee /Smit/", "1 FAMS @F1@"),
              "0 @F1@ FAM\n1 HUSB @I1@\n1 WIFE @I2@\n1 MARR\n2 DATE 14 SEP 1806\n" + _cite())
    result = verify.verify("", new)
    assert result.counts()[verify.CONTRADICTED] == 0 and result.counts()[verify.SUPPORTED] == 1


def test_a_grandsons_marriage_is_no_contradiction_for_the_grandparents(records):
    records[REF] = _record("Huwelijk", (1, 2, 1824), "Drunen", ("Bruidegom", "Jan Dekkers"),
                           ("Bruid", "Johanna Maria Adams"))  # fmt: skip
    new = ged(_person("I1", "Jan /Dekkers/", "1 FAMS @F1@"), _person("I2", "Anna /Smit/", "1 FAMS @F1@"),
              "0 @F1@ FAM\n1 HUSB @I1@\n1 WIFE @I2@\n1 MARR\n2 DATE 17 DEC 1724\n" + _cite())
    result = verify.verify("", new)
    assert result.counts()[verify.CONTRADICTED] == 0 and not result.errors


def test_a_son_named_after_his_father_is_no_contradiction(records):
    records[REF] = _record("Geboorte", (25, 11, 1824), "Drunen", ("Kind", "Jan Dekkers"), ("Vader", "Jan Dekkers"))
    result = verify.verify("", ged(_person("I1", "Jan /Dekkers/", "1 BIRT", "2 DATE ABT 1782", _cite())))
    assert result.counts()[verify.CONTRADICTED] == 0 and not result.errors


def test_birth_bounded_by_baptism(records):
    records[REF] = _record("Doop", (14, 3, 1731), "Breda", ("Kind", "Maria Wouters"), ("Vader", "Peter Wouters"))
    result = verify.verify("", ged(_person("I1", "Maria /Wouters/", "1 BIRT", "2 DATE BEF 15 MAR 1731", _cite())))
    assert result.counts()[verify.SUPPORTED] == 1


def test_wife_named_only_through_her_husband(records):
    records[REF] = _record("Begraven", (3, 5, 1760), "Breda", ("Overledene", "de huisvrouw van Gerrit van Aken"))
    new = ged(
        _person("I1", "Gerrit /van Aken/", "1 FAMS @F1@"),
        _person("I2", "Maria /Bakker/", "1 FAMS @F1@", "1 BURI", "2 DATE 3 MAY 1760", _cite()),
        "0 @F1@ FAM\n1 HUSB @I1@\n1 WIFE @I2@",
    )
    result = verify.verify("", new)
    assert result.counts()[verify.SUPPORTED] == 1


def test_parent_link_needs_child_and_parents(records):
    records[REF] = _record(
        "Doop", (5, 6, 1800), "Breda", ("Kind", "Anna Dekkers"), ("Vader", "Jan Dekkers"), ("Moeder", "Kee Smit"),
    )  # fmt: skip
    family = "0 @F1@ FAM\n1 HUSB @I1@\n1 WIFE @I2@\n1 CHIL @I3@"
    parents = [_person("I1", "Jan /Dekkers/", "1 FAMS @F1@"), _person("I2", "Kee /Smit/", "1 FAMS @F1@")]
    good = ged(*parents, _person("I3", "Anna /Dekkers/", "1 FAMC @F1@", _cite()), family)
    assert verify.verify("", good).counts()[verify.SUPPORTED] == 1
    parents[1] = _person("I2", "Lena /Bos/", "1 FAMS @F1@")
    other = ged(*parents, _person("I3", "Anna /Dekkers/", "1 FAMC @F1@", _cite()), family)
    result = verify.verify("", other)
    assert result.counts()[verify.PARTIAL] == 1
    assert "Lena Bos" in result.warnings[0]


def test_proven_fact_without_resolvable_citation_is_an_error():
    proven = ged(_person("I1", "Jan /Dekkers/", "1 DEAT", "2 DATE 1900", _cite("Genealogie, p. 12")))
    assert verify.verify("", proven).errors
    probable = ged(_person("I1", "Jan /Dekkers/", "1 DEAT", "2 DATE 1900", _cite("Genealogie, p. 12", quay="2")))
    assert not verify.verify("", probable).errors


def test_scan_needs_the_reread_marker():
    page = "RAT 929 (Schepenbank) inv. 145 p. 3 (scan 0012)"
    bare = verify.verify("", ged(_person("I1", "Jan /Dekkers/", "1 DEAT", "2 DATE 1742", _cite(page))))
    assert bare.counts()[verify.UNREREAD] == 1 and bare.warnings
    marked = verify.verify(
        "", ged(_person("I1", "Jan /Dekkers/", "1 DEAT", "2 DATE 1742", _cite(page + "; nagelezen door leider")))
    )
    assert marked.counts()[verify.UNCHECKED] == 1 and not marked.warnings and not marked.errors


def test_newspaper_text(monkeypatch):
    monkeypatch.setattr(verify, "delpher_text", lambda urn, offline=False: "<text><p>Overleden Jan Dekkers 1906</p></text>")
    page = "Krant; https://resolver.kb.nl/resolve?urn=ddd:1:mpeg21:a1"
    result = verify.verify("", ged(_person("I1", "Jan /Dekkers/", "1 DEAT", "2 DATE 2 MAR 1906", _cite(page))))
    assert result.counts()[verify.SUPPORTED] == 1
    result = verify.verify("", ged(_person("I1", "Piet /Smit/", "1 DEAT", "2 DATE 2 MAR 1907", _cite(page))))
    assert result.counts()[verify.PARTIAL] == 1 and not result.errors


def test_record_gone_from_open_archieven_is_unresolvable(records):
    result = verify.verify("", ged(_person("I1", "Jan /Dekkers/", "1 DEAT", "2 DATE 1900", _cite())))
    assert result.counts()[verify.UNRESOLVABLE] == 1 and result.errors


def test_record_not_in_cache_is_not_comparable(monkeypatch):
    def show(ref, offline=False):
        raise archive.NotCached(ref)

    monkeypatch.setattr(archive, "show", show)
    result = verify.verify("", ged(_person("I1", "Jan /Dekkers/", "1 DEAT", "2 DATE 1900", _cite())), offline=True)
    assert result.counts()[verify.UNCHECKED] == 1 and not result.errors


def test_tsv(records):
    records[REF] = _record("Overlijden", (1, 1, 1900), "Breda", ("Overledene", "Jan Dekkers"))
    result = verify.verify("", ged(_person("I1", "Jan /Dekkers/", "1 DEAT", "2 DATE 1 JAN 1900", _cite())))
    header, line = verify.tsv(result).splitlines()
    assert header.split("\t") == list(verify.TSV_COLUMNS)
    assert line.split("\t")[:5] == ["I1", "DEAT", "3", REF, verify.SUPPORTED]


def test_strict_setting(tmp_path: Path):
    file = tmp_path / "lineage.toml"
    file.write_text("[verify]\nstrict = true\n")
    config = settings.parse(file.read_text(), file)
    assert config.verify_strict
    assert "[verify]\nstrict = true" in settings.dump(config)


def _baptism(child: str, father: str, mother: str, date=(5, 6, 1800)) -> Record:
    return _record("Doop", date, "Breda", ("Kind", child), ("Vader", father), ("Moeder", mother))


def _family_tree(child_lines: list[str]) -> str:
    return ged(
        _person("I1", "Jan /Dekkers/", "1 FAMS @F1@"),
        _person("I2", "Kee /Smit/", "1 FAMS @F1@"),
        _person("I3", "Anna /Dekkers/", *child_lines),
        "0 @F1@ FAM\n1 HUSB @I1@\n1 WIFE @I2@\n1 CHIL @I3@",
    )


OTHER = "https://www.openarchieven.nl/abc:99999999-2222-3333-4444-555555555555"
OTHER_REF = "abc:99999999-2222-3333-4444-555555555555"


def test_link_on_one_baptism_and_nothing_else_is_single(records):
    records[REF] = _baptism("Anna Dekkers", "Jan Dekkers", "Kee Smit")
    result = verify.verify("", _family_tree(["1 FAMC @F1@", _cite()]))
    assert result.links["single"] == 1 and not result.errors


def test_link_with_a_death_whose_age_fits_is_independent(records):
    records[REF] = _baptism("Anna Dekkers", "Jan Dekkers", "Kee Smit")
    records[OTHER_REF] = _record("Overlijden", (1, 1, 1860), "Breda", ("Overledene", "Anna Dekkers"))
    records[OTHER_REF].persons[0].age = "59"
    tree = _family_tree(["1 FAMC @F1@", _cite(), "1 DEAT", "2 DATE 1 JAN 1860", _cite(OTHER)])
    result = verify.verify("", tree)
    assert result.links["independent"] == 1 and not result.errors


def test_link_whose_other_records_confirm_nothing_is_weak(records):
    records[REF] = _baptism("Anna Dekkers", "Jan Dekkers", "Kee Smit")
    records[OTHER_REF] = _record("Overlijden", (1, 1, 1860), "Breda", ("Overledene", "Anna Dekkers"))
    records[OTHER_REF].persons[0].age = "30"
    tree = _family_tree(["1 FAMC @F1@", _cite(), "1 DEAT", "2 DATE 1 JAN 1860", _cite(OTHER)])
    result = verify.verify("", tree)
    assert result.links["weak"] == 1
    assert any("FAMC @F1@" in e for e in result.errors)


def test_a_burial_without_age_cannot_make_a_link_weak(records):
    records[REF] = _baptism("Anna Dekkers", "Jan Dekkers", "Kee Smit")
    records[OTHER_REF] = _record("Begraven", (1, 1, 1860), "Breda", ("Overledene", "Anna Dekkers"))
    tree = _family_tree(["1 FAMC @F1@", _cite(), "1 BURI", "2 DATE 1 JAN 1860", _cite(OTHER)])
    assert verify.verify("", tree).links["single"] == 1


def test_an_age_in_words_with_jaar_confirms(records):
    records[REF] = _baptism("Anna Dekkers", "Jan Dekkers", "Kee Smit")
    records[OTHER_REF] = _record("Overlijden", (1, 1, 1880), "Breda", ("Overledene", "Anna Dekkers"))
    records[OTHER_REF].persons[0].age = "80 jaar"
    tree = _family_tree(["1 FAMC @F1@", _cite(), "1 DEAT", "2 DATE 1 JAN 1880", _cite(OTHER)])
    assert verify.verify("", tree).links["independent"] == 1


def test_a_namesake_father_in_a_register_does_not_make_a_link_weak(records):
    records[REF] = _baptism("Anna Dekkers", "Jan Dekkers", "Kee Smit")
    records[OTHER_REF] = _record("Registratie", (None, None, 1830), "Breda", ("Geregistreerde", "Anna Dekkers"))
    records[OTHER_REF].persons[0].birth_date = (1, 1, 1770)
    tree = _family_tree(["1 FAMC @F1@", _cite(), "1 RESI", "2 DATE 1830", _cite(OTHER)])
    assert verify.verify("", tree).links["single"] == 1


def test_the_birthplace_comes_from_the_baptism_when_the_tree_has_none(records):
    records[REF] = _baptism("Anna Dekkers", "Jan Dekkers", "Kee Smit")
    records[OTHER_REF] = _record("Trouwen", (1, 5, 1825), "Breda", ("Bruid", "Anna Dekkers"))
    records[OTHER_REF].persons[0].birth_place = "Breda"
    tree = _family_tree(["1 FAMC @F1@", _cite(), "1 MARR", "2 DATE 1 MAY 1825", _cite(OTHER)])
    assert verify.verify("", tree).links["independent"] == 1


def test_two_indexes_of_one_baptism_count_once(records):
    records[REF] = _baptism("Anna Dekkers", "Jan Dekkers", "Kee Smit")
    records[OTHER_REF] = _baptism("Anna Dekkers", "Jan Dekkers", "Kee Smit")
    text = _family_tree(["1 FAMC @F1@", _cite(), _cite(OTHER)])
    cited = verify.facts(text)
    assert verify.link_support(cited[0], cited, verify.parse(text)) == (1, 0, False)


def test_probable_link_is_not_judged(records):
    records[REF] = _baptism("Anna Dekkers", "Jan Dekkers", "Kee Smit")
    assert not verify.verify("", _family_tree(["1 FAMC @F1@", _cite(quay="1")])).links


def test_uncited_link_is_judged_on_the_childs_records(records):
    records[REF] = _baptism("Anna Dekkers", "Jan Dekkers", "Kee Smit")
    old = _family_tree(["1 BAPM", "2 DATE 5 JUN 1800", _cite()])
    new = _family_tree(["1 FAMC @F1@", "1 BAPM", "2 DATE 5 JUN 1800", _cite()])
    assert verify.verify(old, new).links == {"single": 1}
    assert not verify.verify(new, new).links


def test_year_words_that_do_not_match_the_conversion():
    found = verify.year_readings({"01-scan.md": '- year in words: "1700 Zeeven entagtig" = 1777\n'
                                                '- year in words: "1700 zeven en tachtig" = 1787'})
    assert found == ['01-scan.md: "1700 Zeeven entagtig" is 1787, not 1777']
