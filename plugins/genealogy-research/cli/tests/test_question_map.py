import re

from lineage import question_map
from lineage.gedcom import parse
from tests.conftest import ged, project

# I1 (recent) -> I2 x I3 -> I4 (father of I2, died 1850); I5 is a brother of I2
TREE = (
    "0 @I1@ INDI",
    "1 NAME Child /Now/",
    "1 BIRT",
    "2 DATE 2010",
    "1 FAMC @F1@",
    "0 @I2@ INDI",
    "1 NAME Pete /Old/",
    "1 BIRT",
    "2 DATE 1820",
    "1 DEAT",
    "2 DATE 1880",
    "1 FAMC @F2@",
    "1 FAMS @F1@",
    "0 @I3@ INDI",
    "1 NAME May /Now/",
    "1 BIRT",
    "2 DATE 1980",
    "1 FAMS @F1@",
    "0 @I4@ INDI",
    "1 NAME Jack /Old/",
    "1 BIRT",
    "2 DATE 1790",
    "1 DEAT",
    "2 DATE 1850",
    "1 FAMS @F2@",
    "0 @I5@ INDI",
    "1 NAME Nick /Old/",
    "1 BIRT",
    "2 DATE 1822",
    "1 DEAT",
    "2 DATE 1890",
    "1 FAMC @F2@",
    "0 @F1@ FAM",
    "1 HUSB @I2@",
    "1 WIFE @I3@",
    "1 CHIL @I1@",
    "0 @F2@ FAM",
    "1 HUSB @I4@",
    "1 CHIL @I2@",
    "1 CHIL @I5@",
)
QUESTIONS = """# Open vragen
## Uit te zoeken met online bronnen
### Oud
- [ ] I4: find the baptism of Jack.
- [ ] I5: marriage of brother Nick.
- [ ] I3: something about May.
- [x] I4: burial found.
## Levende personen of recent (niet opzoeken)
### Oud
- [ ] I3: address.
"""


def build(**kw):
    tree = parse(ged(*TREE))
    old = question_map.LINE_GENERATION
    question_map.LINE_GENERATION = 1
    try:
        return question_map.build(tree, QUESTIONS, "I1", **kw)
    finally:
        question_map.LINE_GENERATION = old


def test_names_only_for_those_who_died_before_1900():
    d = build()
    assert d["persons"]["I4"]["name"] == "Jack Old"
    assert d["persons"]["I3"]["name"] is None and d["persons"]["I3"]["questions"] == []


def test_own_and_side_branch_questions_counted_and_living_skipped():
    d = build()
    jack = d["persons"]["I4"]
    assert (jack["own"], jack["side_branch"]) == (1, 1)
    assert [q["how"] for q in jack["questions"]] == ["own", "side_branch"]
    assert d["persons"]["I4"]["gap"] == 2
    assert d["totals"]["open"] == 3 and d["totals"]["solved"] == 1
    assert sum(c["open"] for c in d["cells"].values()) == 3


def test_history_replaces_the_same_day(tmp_path):
    path = tmp_path / "h.tsv"
    question_map.update_history(path, {"date": "2026-10-29", "open": 5})
    rows = question_map.update_history(path, {"date": "2026-10-29", "open": 4})
    assert rows == [{"date": "2026-10-29", "open": 4}]


def test_history_reads_the_dutch_header(tmp_path):
    path = tmp_path / "h.tsv"
    path.write_text("datum\topen\topgelost\n2026-10-28\t5\t2\n", encoding="utf-8")
    rows = question_map.update_history(path, {"date": "2026-10-29", "open": 4, "solved": 3})
    assert rows == [
        {"date": "2026-10-28", "open": 5, "solved": 2},
        {"date": "2026-10-29", "open": 4, "solved": 3},
    ]


def test_page_is_written_in_the_project_language(tmp_path):
    project(tmp_path, language="nl")
    out = tmp_path / "kaart.html"
    question_map.write(
        build(), [{"date": "2026-10-29", "open": 1, "solved": 0, "gaps": 0}], out, "Familie Test"
    )
    page = out.read_text(encoding="utf-8")
    assert "Waar de open vragen zitten" in page and "Familie Test · kwartierstaat vanaf I1" in page
    assert (
        not re.search(r"\[\[[a-z_]+\]\]", page)
        and "__LABELS__" not in page
        and "__DATA__" not in page
    )
    assert '"locale":"nl-NL"' in page and "Vaderskant" in page


def test_page_in_english_has_no_project_text(tmp_path):
    project(tmp_path)
    out = tmp_path / "map.html"
    question_map.write(build(), [{"date": "2026-10-29", "open": 1, "solved": 0, "gaps": 0}], out)
    page = out.read_text(encoding="utf-8")
    assert (
        "Where the open questions are" in page
        and "Family research · ancestor table from I1" in page
    )
    assert not re.search(r"\[\[[a-z_]+\]\]", page)
