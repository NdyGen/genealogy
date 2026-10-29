import pytest

from lineage import build, edit, settings
from lineage.cli import main
from lineage.gedcom import load


@pytest.mark.parametrize(
    "spoken, gedcom",
    [
        ("1950", "1950"),
        ("12-3-1950", "12 MAR 1950"),
        ("1950-03-12", "12 MAR 1950"),
        ("12 maart 1950", "12 MAR 1950"),
        ("March 12, 1950", "12 MAR 1950"),
        ("mei 1890", "MAY 1890"),
        ("omstreeks 1890", "ABT 1890"),
        ("about 1890", "ABT 1890"),
        ("vóór 1900", "BEF 1900"),
        ("tussen 1880 en 1885", "BET 1880 AND 1885"),
        ("ABT 3 MAR 1820", "ABT 3 MAR 1820"),
    ],
)
def test_dates_as_people_write_them(spoken, gedcom):
    assert build.gedcom_date(spoken) == gedcom


def test_an_unreadable_date_is_refused():
    with pytest.raises(build.BuildError, match="cannot read the date"):
        build.gedcom_date("in the war")


def test_a_tree_from_scratch(tmp_path, capsys):
    path = tmp_path / "data" / "tree.ged"
    build.new_tree(path)
    lines = edit.read(path)
    me = build.add_person(lines, "Anna", "Visser", "F", [build.Event("BIRT", "1980", "Utrecht")], source="Own knowledge")
    father = build.add_person(
        lines, "Jan", "Visser", "M",
        [build.Event("BIRT", "12-3-1950", "Zwolle"), build.Event("DEAT")],
        occupation="teacher", source="Told by Els Visser (aunt), 2026",
    )  # fmt: skip
    mother = build.add_person(lines, "Els", "de Boer", "F", source="Told by Els Visser (aunt), 2026")
    family = build.add_family(lines, [mother, father], [me], build.Event("MARR", "1975", "Zwolle"))
    edit.write(path, lines)
    tree = load(path)
    assert (me, father, mother, family) == ("I1", "I2", "I3", "F1")
    assert tree.families["F1"].partners == ["I2", "I3"]
    assert [p.id for p in tree.parents("I1")] == ["I2", "I3"]
    assert str(tree.persons["I2"].birth_date) == "12 MAR 1950"
    assert sum(1 for line in lines if line.startswith("0 @S")) == 2
    assert "1 DEAT Y" in lines


def test_cli_builds_and_keeps_a_broken_change_out(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["init", "--new-tree", "--language", "nl"]) == 0
    assert (tmp_path / "data/tree.ged").exists()
    settings.use(None)
    assert main(["add", "person", "--given", "Piet", "--surname", "Kok", "--sex", "M", "--born", "omstreeks 1890",
                 "--born-place", "Delft", "--deceased", "--source", "Bidprentje"]) == 0  # fmt: skip
    assert main(["add", "person", "--given", "Kees", "--surname", "Kok", "--born", "1920"]) == 0
    assert main(["add", "family", "--partner", "I1", "--child", "I2"]) == 0
    assert "Piet Kok [I1]" in capsys.readouterr().out
    assert main(["add", "child", "F1", "I9"]) == 2
    assert "I9" in capsys.readouterr().err
    tree = load(tmp_path / "data/tree.ged")
    assert [p.id for p in tree.parents("I2") if p] == ["I1"]
    assert main(["add", "person", "--given", "X", "--born", "ooit"]) == 2
    assert "kan de datum 'ooit' niet lezen" in capsys.readouterr().err
