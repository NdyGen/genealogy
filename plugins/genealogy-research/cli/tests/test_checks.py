from lineage.checks import Level, check
from lineage.gedcom import parse
from tests.conftest import ged, project


def messages(text: str, level: Level = Level.WARNING) -> list[str]:
    return [f"{f.subject}: {f.message}" for f in check(parse(text)) if f.level <= level]


def family(husband_birth: str, wife_birth: str, child_birth: str, *extra: str) -> str:
    return ged(
        "0 @I1@ INDI", "1 NAME Father /A/", "1 SEX M", "1 BIRT", f"2 DATE {husband_birth}", "1 FAMS @F1@",
        "0 @I2@ INDI", "1 NAME Mother /B/", "1 SEX F", "1 BIRT", f"2 DATE {wife_birth}", "1 FAMS @F1@",
        *extra,
        "0 @I3@ INDI", "1 NAME Child /A/", "1 BIRT", f"2 DATE {child_birth}", "1 FAMC @F1@",
        "0 @F1@ FAM", "1 HUSB @I1@", "1 WIFE @I2@", "1 CHIL @I3@",
    )  # fmt: skip


def test_clean_tree_has_no_errors_or_warnings(tree):
    assert [f for f in check(tree) if f.level <= Level.WARNING] == []


def test_death_before_birth():
    found = messages(ged("0 @I1@ INDI", "1 BIRT", "2 DATE 1900", "1 DEAT", "2 DATE 1890"))
    assert found == ["I1: died (1890) before birth (1900)"]


def test_parent_too_young():
    assert messages(family("1880", "1850", "1890")) == [
        "F1: Father A was at most 10 years old at the birth of Child A"
    ]


def test_approximate_dates_do_not_raise_false_alarms():
    assert messages(family("ABT 1872", "1860", "1885")) == []


def test_mother_too_old():
    assert messages(family("1840", "1830", "1885")) == [
        "F1: Mother B was at least 55 years old at the birth of Child A"
    ]


def test_child_born_after_mother_died():
    found = messages(family("1850", "1850", "1885"), level=Level.ERROR)
    assert found == []
    text = family("1850", "1850", "1885").replace(
        "1 NAME Mother /B/", "1 NAME Mother /B/\n1 DEAT\n2 DATE 1880"
    )
    assert messages(text, level=Level.ERROR) == [
        "F1: Child A born (1885) after the death of Mother B"
    ]


def test_father_may_die_shortly_before_birth():
    text = family("1850", "1850", "1885").replace(
        "1 NAME Father /A/", "1 NAME Father /A/\n1 DEAT\n2 DATE 1884"
    )
    assert messages(text, level=Level.ERROR) == []


def test_one_sided_link_is_an_error():
    text = ged("0 @I1@ INDI", "1 FAMC @F1@", "0 @F1@ FAM")
    assert messages(text, Level.ERROR) == [
        "I1: refers to family F1, which does not list them as a child"
    ]


def test_missing_references():
    text = ged("0 @I1@ INDI", "1 FAMS @F9@", "1 SOUR @S9@", "0 @F1@ FAM", "1 CHIL @I9@")
    assert messages(text, Level.ERROR) == [
        "F1: unknown child I9",
        "I1: partner in unknown family F9",
        "I1: refers to unknown source S9",
    ]


def test_unreadable_date():
    text = ged("0 @I1@ INDI", "1 OCCU", "2 DATE SERVANT")
    assert messages(text) == ["I1: unreadable date 'SERVANT' for occupation"]


def test_format_problem_is_an_error():
    text = ged("0 @I1@ INDI", "1 NOTE a", "stray line")
    assert messages(text, Level.ERROR)[0].startswith("GEDCOM: line 4")


def test_possible_duplicate():
    text = ged("0 @I1@ INDI", "1 NAME John /Smith/", "1 BIRT", "2 DATE 1850",
               "0 @I2@ INDI", "1 NAME John /Smith/", "1 BIRT", "2 DATE 1851")  # fmt: skip
    assert messages(text) == ["I1: possibly the same person as I2 (John Smith)"]


def test_name_reused_after_child_died_is_not_a_duplicate():
    text = ged("0 @I1@ INDI", "1 NAME John /Smith/", "1 BIRT", "2 DATE 1850", "1 DEAT", "2 DATE 1850",
               "0 @I2@ INDI", "1 NAME John /Smith/", "1 BIRT", "2 DATE 1851")  # fmt: skip
    assert messages(text) == []


def test_missing_sources_are_info(tree):
    info = {f.subject: f.message for f in check(tree) if f.level == Level.INFO}
    assert info["I7"] == "no citation at all"
    assert info["I2"] == "without source: died"


def test_glued_line_is_an_error():
    text = ged("0 @I1@ INDI", "1 RELI 1 FAMC @F1@", "0 @F1@ FAM", "1 CHIL @I1@")
    assert any("glued line after RELI" in m for m in messages(text, Level.ERROR))


def test_note_starting_with_number_is_not_glued():
    text = ged("0 @I1@ INDI", "1 NOTE 3 children, 1 JAN 1850 baptized")
    assert messages(text, Level.ERROR) == []


def test_duplicate_xref_is_an_error():
    text = ged("0 @S1@ SOUR", "1 TITL a", "0 @S1@ SOUR", "1 TITL a")
    assert messages(text, Level.ERROR) == ["GEDCOM: ID S1 occurs more than once"]


def test_multiple_births_are_a_warning():
    text = ged("0 @I1@ INDI", "1 BIRT", "2 DATE 1850", "1 BIRT", "2 DATE 1852")
    assert messages(text) == ["I1: birth recorded 2 times"]


def test_namesakes_with_own_baptism_records_are_not_duplicates():
    text = ged(
        "0 @I1@ INDI", "1 NAME John /Smith/", "1 CHR", "2 DATE 1850", "2 SOUR @S1@", "3 PAGE baptism 1850, record 3",
        "0 @I2@ INDI", "1 NAME John /Smith/", "1 CHR", "2 DATE 1851", "2 SOUR @S1@", "3 PAGE baptism 1851, record 9",
        "0 @S1@ SOUR",
    )  # fmt: skip
    assert messages(text) == []


def test_same_baptism_record_is_still_a_duplicate():
    text = ged(
        "0 @I1@ INDI", "1 NAME John /Smith/", "1 CHR", "2 DATE 1850", "2 SOUR @S1@", "3 PAGE record 3",
        "0 @I2@ INDI", "1 NAME John /Smith/", "1 CHR", "2 DATE 1850", "2 SOUR @S1@", "3 PAGE record 3",
        "0 @S1@ SOUR",
    )  # fmt: skip
    assert messages(text) == ["I1: possibly the same person as I2 (John Smith)"]


def test_smart_match_names_do_not_count_as_records():
    text = ged(
        "0 @I1@ INDI", "1 NAME John /Smith/", "1 BIRT", "2 DATE 1850", "2 SOUR @S1@", "3 PAGE John Smith",
        "0 @I2@ INDI", "1 NAME John /Smith/", "1 BIRT", "2 DATE 1851", "2 SOUR @S1@", "3 PAGE William Smith",
        "0 @S1@ SOUR",
    )  # fmt: skip
    assert messages(text) == ["I1: possibly the same person as I2 (John Smith)"]


def test_namesakes_with_different_parents_are_not_duplicates():
    text = ged(
        "0 @I1@ INDI", "1 NAME John /Smith/", "1 BIRT", "2 DATE 1850", "1 FAMC @F1@",
        "0 @I2@ INDI", "1 NAME John /Smith/", "1 BIRT", "2 DATE 1851", "1 FAMC @F2@",
        "0 @F1@ FAM", "1 CHIL @I1@", "0 @F2@ FAM", "1 CHIL @I2@",
    )  # fmt: skip
    assert messages(text) == []


def test_findings_are_dutch_in_a_dutch_project(tmp_path):
    project(tmp_path, language="nl")
    found = messages(ged("0 @I1@ INDI", "1 BIRT", "2 DATE 1900", "1 DEAT", "2 DATE 1890"))
    assert found == ["I1: overleden (1890) vóór geboorte (1900)"]
