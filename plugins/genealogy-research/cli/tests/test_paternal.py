import datetime as dt

from lineage import paternal, requests
from lineage.gedcom import parse
from tests.conftest import ged, project


def _tree(with_great_grandfather: bool):
    lines = [
        "0 @I1@ INDI", "1 NAME Child /D/", "1 SEX M", "1 FAMC @F1@",
        "0 @I2@ INDI", "1 NAME Father /D/", "1 SEX M", "1 FAMS @F1@", "1 FAMC @F2@",
        "0 @I3@ INDI", "1 NAME Mother /X/", "1 SEX F", "1 FAMS @F1@",
        "0 @I4@ INDI", "1 NAME Grandpa /D/", "1 SEX M", "1 FAMS @F2@",
        "1 BIRT", "2 DATE ABT 1600", "2 PLAC Northfield",
        "0 @F1@ FAM", "1 HUSB @I2@", "1 WIFE @I3@", "1 CHIL @I1@",
        "0 @F2@ FAM", "1 HUSB @I4@", "1 CHIL @I2@",
    ]  # fmt: skip
    if with_great_grandfather:
        lines[lines.index("0 @I4@ INDI") + 3 : lines.index("0 @I4@ INDI") + 3] = ["1 FAMC @F3@"]
        lines += ["0 @I5@ INDI", "1 NAME Great-grandfather /D/", "1 SEX M", "1 FAMS @F3@",
                  "0 @F3@ FAM", "1 HUSB @I5@", "1 CHIL @I4@"]  # fmt: skip
    return parse(ged(*lines))


def test_line_follows_fathers_only():
    assert paternal.line(_tree(False), "I1") == ["I1", "I2", "I4"]


def test_new_generations_only_when_extended():
    assert paternal.new_generations(["I1", "I2"], ["I1", "I2", "I4"]) == ["I4"]
    assert paternal.new_generations(["I1", "I2", "I4"], ["I1", "I2"]) == []
    assert paternal.new_generations(["I1", "I2", "I4"], ["I1", "I2", "I9", "I10"]) == []


def test_draft_is_a_valid_request(tmp_path):
    project(tmp_path, sender_name="Ann Doe")
    tree = _tree(True)
    path = paternal.draft(
        tree,
        ["I1", "I2", "I4"],
        paternal.line(tree, "I1"),
        "me@example.org",
        tmp_path,
        dt.date(2026, 10, 16),
    )
    request = requests.read(path)
    assert request.to == "me@example.org" and request.status == "draft"
    assert request.subject == "D paternal line extended: Great-grandfather D (I5)"
    text = path.read_text()
    assert "Grandpa D (I4)" in text and "(from Child D, I1)" in text and text.count("Ann Doe") == 2


def test_draft_header_uses_the_english_keys(tmp_path):
    project(tmp_path)
    tree = _tree(True)
    path = paternal.draft(
        tree,
        ["I1", "I2", "I4"],
        paternal.line(tree, "I1"),
        "me@example.org",
        tmp_path,
        dt.date(2026, 10, 16),
    )
    header = path.read_text().split("\n---\n")[0]
    assert "to: " in header and "subject: " in header and "status: draft" in header
    assert "aan:" not in header and "onderwerp:" not in header


def test_draft_in_dutch(tmp_path):
    project(tmp_path, language="nl", sender_name="Ann Doe")
    tree = _tree(True)
    path = paternal.draft(
        tree,
        ["I1", "I2", "I4"],
        paternal.line(tree, "I1"),
        "me@example.org",
        tmp_path,
        dt.date(2026, 10, 16),
    )
    text = path.read_text()
    assert "subject: D-vaderlijn verlengd: Great-grandfather D (I5)" in text
    assert "is 1 generatie(s) langer geworden" in text and "Nieuw in de lijn:" in text
    assert "geboren/gedoopt" in text or "geen levensdata vastgelegd" in text
    assert "status: draft" in text and "aan:" not in text
