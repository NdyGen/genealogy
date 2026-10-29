import datetime as dt

from lineage import book
from lineage.cli import main
from lineage.gedcom import load, parse
from tests.conftest import FIXTURE, ged, project

TODAY = dt.date(2026, 10, 1)
STORY = """# Henry Miller (1860-1930)

*Grandfather of John Miller (I1).*

Henry was a farmer.

## On the farm

![The farm](images/I4/farm.jpg)

See also [his son](I2.md).

---

**Sources:** birth record 1860.

**Background** (on the period): [Wikipedia](https://en.wikipedia.org/wiki/Farmer).
"""


def _book(tree, tmp_path, target="I1"):
    stories = tmp_path / "life-stories"
    stories.mkdir(exist_ok=True)
    (stories / "I4.md").write_text(STORY, encoding="utf-8")
    return book.build(tree, target, stories=stories, reports=tmp_path / "persons", today=TODAY)


def test_patriline_follows_fathers(tree):
    assert [p.id for p in book.patriline(tree, "I1")] == ["I1", "I2", "I4"]


def test_plain_dates():
    assert book.plain_date("BEF 19 OCT 1914") == "before 19 October 1914"
    assert book.plain_date("BET 1751 AND 1752") == "between 1751 and 1752"
    assert book.plain_date("FROM 1856 TO 1891") == "from 1856 to 1891"


def test_parts_are_ordered_oldest_first_with_mother_in_part_two(tree, tmp_path):
    text = _book(tree, tmp_path)
    part1, part2 = text.split("# Part I. ")[1].split("# Part II. ")
    assert part1.index('id="I4"') < part1.index('id="I2"')
    assert 'id="I3"' in part2 and 'id="I4"' not in part2


def test_story_is_cleaned_and_rebased(tree, tmp_path):
    text = _book(tree, tmp_path)
    chapter = text.split('id="I4"')[1].split('id="I2"')[0]
    assert "Henry was a farmer." in chapter
    assert "Grandfather of John" not in chapter
    assert "**Sources:**" not in chapter
    assert "### On the farm" in chapter
    assert "](../life-stories/images/I4/farm.jpg)" in chapter
    assert "[his son](#I2)" in chapter
    assert "**Background**" in chapter


def test_line_and_support_under_each_story(tree, tmp_path):
    text = _book(tree, tmp_path)
    chapter = text.split('id="I4"')[1].split('id="I2"')[0]
    line = chapter.split("### Line to John Miller")[1].split("###")[0]
    assert "1. Henry Miller (1860-1930) [I4], grandfather" in line
    assert "2. William Miller (1890-1960) [I2], father" in line
    assert "3. John Miller [I1]" in line
    support = chapter.split("### Supporting facts")[1]
    assert "- born: 1860" in support and "Source:" in support


def test_missing_story_is_listed_as_gap(tree, tmp_path):
    text = _book(tree, tmp_path)
    assert "No life story has been written" in text.split('id="I2"')[1]
    assert "William Miller (1890-1960) [I2]" in text.split("# Still to write")[1]


def test_possibly_living_people_get_no_story_or_facts(tmp_path):
    tree = parse(
        ged(
            "0 @C@ INDI",
            "1 NAME Child /Jones/",
            "1 SEX M",
            "1 FAMC @F1@",
            "0 @V@ INDI",
            "1 NAME Father /Jones/",
            "1 SEX M",
            "1 BIRT",
            "2 DATE 1960",
            "1 FAMS @F1@",
            "1 FAMC @F2@",
            "0 @G@ INDI",
            "1 NAME Grandpa /Jones/",
            "1 SEX M",
            "1 BIRT",
            "2 DATE 1900",
            "1 DEAT",
            "2 DATE 1980",
            "1 FAMS @F2@",
            "0 @F1@ FAM",
            "1 HUSB @V@",
            "1 CHIL @C@",
            "0 @F2@ FAM",
            "1 HUSB @G@",
            "1 CHIL @V@",
        )
    )
    text = book.build(tree, "C", stories=tmp_path, reports=tmp_path, today=TODAY)
    father = text.split('id="V"')[1].split("<a id=")[0]
    assert "Possibly living" in father and "### Supporting facts" not in father
    assert "## Father Jones\n" in father and "1960" not in father
    assert "Father Jones](#V) (living)" in text
    assert "Grandpa Jones (1900-1980) [G]" in text.split("# Still to write")[1]


def test_cli_writes_book(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["--file", str(FIXTURE), "book", "I1"]) == 0
    assert (
        (tmp_path / "reports/books/I1.md").read_text(encoding="utf-8").startswith("# Life stories")
    )


def test_plain_date_in_dutch(tmp_path):
    project(tmp_path, language="nl")
    assert book.plain_date("BEF 2 SEP 1832") == "vóór 2 september 1832"
    assert book.plain_date("ABT 1750") == "omstreeks 1750"
    assert book.plain_date("BET 1751 AND 1752") == "tussen 1751 en 1752"
    assert book.plain_date("FROM 1856 TO 1891") == "van 1856 tot 1891"
    assert book.plain_date("FROM 1856") == "vanaf 1856"


def test_dutch_book_headings(tmp_path):
    project(tmp_path, language="nl")
    text = book.build(
        load(FIXTURE), "I1", tmp_path / "stories", tmp_path / "reports", today=dt.date(2026, 10, 29)
    )
    assert text.startswith("# Levensverhalen van de voorouders van John Miller")
    assert "Samengesteld uit het stamboomonderzoek op 29-10-2026" in text
    assert "## Inhoud" in text and "**Deel I. De vaderlijke lijn van John Miller**" in text
    assert "Voor deze persoon is nog geen levensverhaal geschreven" in text
    assert "### Onderbouwing" in text and "Bron:" in text and "# Nog te schrijven" in text
