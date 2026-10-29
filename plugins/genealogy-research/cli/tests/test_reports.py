from lineage import graph, reports
from lineage.cli import main
from lineage.gedcom import parse
from tests.conftest import FIXTURE, ged, project


def test_numbered_ancestors_numbering(tree):
    numbers = {a.number: a.person.id for a in reports.numbered_ancestors(tree, "I1", 5)}
    assert numbers == {1: "I1", 2: "I2", 3: "I3", 4: "I4", 5: "I5"}


def test_numbered_ancestors_respects_generations(tree):
    assert {a.person.id for a in reports.numbered_ancestors(tree, "I1", 2)} == {"I1", "I2", "I3"}


def test_pedigree_collapse_refers_to_first_number():
    # I1's parents are cousins: I4 is grandparent on both sides.
    text = ged(
        "0 @I1@ INDI", "1 FAMC @F1@",
        "0 @I2@ INDI", "1 FAMC @F2@", "1 FAMS @F1@",
        "0 @I3@ INDI", "1 SEX F", "1 FAMC @F3@", "1 FAMS @F1@",
        "0 @I4@ INDI", "1 FAMS @F2@", "1 FAMS @F3@",
        "0 @F1@ FAM", "1 HUSB @I2@", "1 WIFE @I3@", "1 CHIL @I1@",
        "0 @F2@ FAM", "1 HUSB @I4@", "1 CHIL @I2@",
        "0 @F3@ FAM", "1 HUSB @I4@", "1 CHIL @I3@",
    )  # fmt: skip
    ancestors = reports.numbered_ancestors(parse(text), "I1", 5)
    assert [(a.number, a.person.id, a.same_as) for a in ancestors if a.person.id == "I4"] == [
        (4, "I4", None),
        (6, "I4", 4),
    ]


def test_ancestor_table_text(tree):
    text = reports.ancestor_table(tree, "I1", 3)
    assert text.startswith("Generation I\n     1. John Miller [I1] (* 3 MAR 1920 Northfield)")
    assert "Generation III" in text
    assert "     5. Anna Taylor [I5] (* 1862, † BEF 1940)" in text


def test_descendant_table_includes_partner_and_children(tree):
    text = reports.descendant_table(tree, "I4", 4)
    assert "I. Henry Miller [I4]" in text
    assert "x: Anna Taylor [I5]" in text
    assert "III. John Miller [I1]" in text
    assert "IV. James Miller [I7]" in text


def test_search_ignores_case_and_diacritics():
    tree = parse(ged("0 @I1@ INDI", "1 NAME Hélène /Van Berg/"))
    assert [p.id for p in reports.search(tree, "helene BERG")] == ["I1"]


def test_person_card_strips_html_from_notes():
    tree = parse(ged("0 @I1@ INDI", "1 NAME John /Smith/", "1 NOTE <p>Record</p>"))
    assert "note: Record" in reports.person_card(tree, "I1")


def test_dot_for_ancestors(tree):
    dot = graph.to_dot(tree, *graph.ancestors(tree, "I1", 3))
    assert '"I4" -> "F2";' in dot
    assert '"F2" -> "I2";' in dot
    assert "I7" not in dot


def test_dot_for_descendants(tree):
    persons, families = graph.descendants(tree, "I2", 3)
    assert persons == {"I1", "I2", "I3", "I6", "I7"}
    assert families == {"F1", "F3"}


def test_cli_validate_exit_code(capsys):
    assert main(["--file", str(FIXTURE), "validate"]) == 0
    assert "0 error, 0 warning" in capsys.readouterr().out


def test_cli_missing_file(tmp_path):
    assert main(["--file", str(tmp_path / "missing.ged"), "summary"]) == 2


def test_cli_tree_writes_dot(tmp_path, capsys):
    target = tmp_path / "tree.dot"
    assert main(["--file", str(FIXTURE), "tree", "i1", "--out", str(target)]) == 0
    assert target.read_text().startswith("digraph tree")


def test_dutch_tables_and_overview(tree, tmp_path):
    project(tmp_path, language="nl")
    text = reports.ancestor_table(tree, "I1", 3)
    assert text.startswith("Generatie I\n     1. John Miller [I1] (* 3 MAR 1920 Northfield)")
    assert "Generatie III" in text
    lines = reports.overview(tree).splitlines()
    assert lines[0].startswith("personen:  ") and lines[1].startswith("gezinnen:  ")
    assert any(line.startswith("controle:  ") for line in lines)
    card = reports.person_card(tree, "I1").splitlines()
    assert card[1] == "  geslacht: M" and "  ouders:" in card
