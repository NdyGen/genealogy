import pytest

from lineage import kinship, settings
from lineage.gedcom import Person, parse
from lineage.kinship import describe
from tests.conftest import ged, project


def test_relations_in_fixture(tree):
    assert describe(tree, "I2", "I1") == "father"
    assert describe(tree, "I4", "I1") == "grandfather"
    assert describe(tree, "I5", "I1") == "grandmother"
    assert describe(tree, "I7", "I4") == "great-grandchild"
    assert describe(tree, "I6", "I1") == "partner"
    assert describe(tree, "I1", "I1") == "the person themselves"


def test_sibling_of_ancestor_and_partner():
    text = ged(
        "0 @I1@ INDI", "1 NAME Me /A/", "1 SEX M", "1 FAMC @F2@",
        "0 @I2@ INDI", "1 NAME Father /A/", "1 SEX M", "1 FAMC @F1@", "1 FAMS @F2@",
        "0 @I3@ INDI", "1 NAME Uncle /A/", "1 SEX M", "1 FAMC @F1@", "1 FAMS @F3@",
        "0 @I4@ INDI", "1 NAME Grandpa /A/", "1 SEX M", "1 FAMS @F1@",
        "0 @I5@ INDI", "1 NAME Aunt /B/", "1 SEX F", "1 FAMS @F3@",
        "0 @I6@ INDI", "1 NAME Cousin /A/", "1 SEX M", "1 FAMC @F3@",
        "0 @I7@ INDI", "1 NAME Stranger /C/",
        "0 @F1@ FAM", "1 HUSB @I4@", "1 CHIL @I2@", "1 CHIL @I3@",
        "0 @F2@ FAM", "1 HUSB @I2@", "1 CHIL @I1@",
        "0 @F3@ FAM", "1 HUSB @I3@", "1 WIFE @I5@", "1 CHIL @I6@",
    )  # fmt: skip
    tree = parse(text)
    assert describe(tree, "I3", "I1") == "brother of your father Father A"
    assert describe(tree, "I6", "I1") == "son of the brother of your father Father A"
    assert describe(tree, "I5", "I1") == "wife of Uncle A, brother of your father Father A"
    assert describe(tree, "I7", "I1") is None


def test_cli_uses_the_targets_and_names_a_missing_one(tmp_path, monkeypatch, capsys):
    from lineage import cli
    from tests.conftest import FIXTURE

    monkeypatch.chdir(tmp_path)
    (tmp_path / "lineage.toml").write_text('targets = [{ label = "Father", id = "I2" }]\n')
    assert cli.main(["--file", str(FIXTURE), "kinship", "I1"]) == 0
    assert "(I2): son" in capsys.readouterr().out
    settings.use(None)
    (tmp_path / "lineage.toml").write_text('targets = [{ label = "Nobody", id = "I999" }]\n')
    with pytest.raises(SystemExit, match="target person I999"):
        cli.main(["--file", str(FIXTURE), "kinship", "I1"])
    settings.use(None)
    (tmp_path / "lineage.toml").write_text("")
    assert cli.main(["--file", str(FIXTURE), "kinship", "I1"]) == 2
    assert "'targets' is not set" in capsys.readouterr().err


NL_TREE = (
    "0 @I1@ INDI", "1 NAME Me /A/", "1 SEX M", "1 FAMC @F2@",
    "0 @I2@ INDI", "1 NAME Father /A/", "1 SEX M", "1 FAMC @F1@", "1 FAMS @F2@",
    "0 @I3@ INDI", "1 NAME Uncle /A/", "1 SEX M", "1 FAMC @F1@", "1 FAMS @F3@",
    "0 @I4@ INDI", "1 NAME Grandpa /A/", "1 SEX M", "1 FAMS @F1@", "1 FAMC @F4@",
    "0 @I5@ INDI", "1 NAME Aunt /B/", "1 SEX F", "1 FAMS @F3@",
    "0 @I6@ INDI", "1 NAME Cousin /A/", "1 SEX F", "1 FAMC @F3@", "1 FAMS @F5@",
    "0 @I8@ INDI", "1 NAME Great /A/", "1 SEX F", "1 FAMS @F4@",
    "0 @I9@ INDI", "1 NAME Kid /A/", "1 FAMC @F5@",
    "0 @F1@ FAM", "1 HUSB @I4@", "1 CHIL @I2@", "1 CHIL @I3@",
    "0 @F4@ FAM", "1 WIFE @I8@", "1 CHIL @I4@",
    "0 @F2@ FAM", "1 HUSB @I2@", "1 CHIL @I1@",
    "0 @F3@ FAM", "1 HUSB @I3@", "1 WIFE @I5@", "1 CHIL @I6@",
    "0 @F5@ FAM", "1 WIFE @I6@", "1 CHIL @I9@",
)  # fmt: skip


@pytest.mark.parametrize(
    "pid, ref, expected",
    [
        ("I1", "I1", "de persoon zelf"),
        ("I2", "I1", "vader"),
        ("I3", "I1", "broer van je vader Father A"),
        ("I4", "I9", "overgrootvader"),
        ("I8", "I9", "betovergrootmoeder"),
        ("I5", "I1", "echtgenote van Uncle A, broer van je vader Father A"),
        ("I9", "I1", "kind van de dochter van de broer van je vader Father A"),
        ("I1", "I9", "zoon van de broer van je grootvader Uncle A"),
        ("I6", "I9", "moeder"),
    ],
)
def test_dutch_terms_are_what_the_dutch_generator_wrote(tmp_path, pid, ref, expected):
    project(tmp_path, language="nl")
    assert describe(parse(ged(*NL_TREE)), pid, ref) == expected


def test_dutch_generation_words(tmp_path):
    project(tmp_path, language="nl")
    mother, man = Person(id="X", sex="F"), Person(id="Y", sex="M")
    assert kinship.ancestor_term(mother, 5) == "oudmoeder"
    assert kinship.ancestor_term(man, 9) == "stamvader"
    assert kinship.ancestor_term(mother, 14) == "voormoeder in de 14e generatie"
    assert kinship.descendant_term(man, 2) == "kleinkind"
    assert kinship.descendant_term(man, 7) == "afstammeling in de 7e generatie"
