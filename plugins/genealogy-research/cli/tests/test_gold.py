import json
from pathlib import Path

import pytest

from lineage import gold
from lineage.gedcom import parse

FIXTURE = Path(__file__).parents[2] / "skills" / "deep-research" / "evals" / "fixture"


@pytest.fixture
def gold_set():
    return gold.load(FIXTURE / "gold.toml")


@pytest.fixture
def tree():
    return (FIXTURE / "tree.ged").read_text(encoding="utf-8")


def _verdicts(score: gold.Score) -> dict[tuple[str, str], str]:
    return {(o.person, o.what): o.verdict for o in score.outcomes if not o.extra}


def test_the_gold_set_loads(gold_set):
    assert [p.id for p in gold_set] == ["I2", "I4"]
    assert gold_set[0].parents[0].name == "John Miller" and gold_set[1].tags == ["BIRT", "DEAT"]


def test_the_exam_strips_gold_facts_and_parent_links(gold_set, tree):
    text = gold.exam(tree, gold_set)
    exam = parse(text)
    william = exam.persons["I2"]
    assert not william.events and william.child_of == [] and william.spouse_in == ["F2"]
    assert exam.parents("I2") == (None, None) and exam.parents("I4") == (None, None)
    assert "I2" not in exam.families["F1"].children
    assert exam.persons["I1"].event("BIRT") and exam.families["F2"].event("MARR")
    assert "NAME William /Miller/" in text


def test_the_tree_itself_scores_against_its_gold(gold_set, tree):
    score = gold.score(tree, gold_set)
    verdicts = _verdicts(score)
    assert verdicts[("I2", "BIRT")] == gold.RIGHT and verdicts[("I4", "DEAT")] == gold.VAGUE
    assert verdicts[("I2", "father")] == gold.RIGHT and verdicts[("I4", "mother")] == gold.RIGHT
    assert score.precision() == 1 and score.recall() == 4 / 5
    assert score.precision(links=True) == 1 and score.recall(links=True) == 1
    assert score.calibration() == {"-": (4, 4), "3": (4, 4)}


def test_the_exam_scores_nothing(gold_set, tree):
    score = gold.score(gold.exam(tree, gold_set), gold_set)
    assert set(_verdicts(score).values()) == {gold.MISSING}
    assert score.precision() is None and score.recall() == 0 and score.recall(links=True) == 0


def test_a_wrong_date_an_extra_fact_and_a_wrong_father_count_against(gold_set, tree):
    wrong = tree.replace("2 DATE 12 NOV 1888", "2 DATE 12 NOV 1887").replace(
        "1 FAMC @F1@\n", "1 FAMC @F1@\n1 DEAT\n2 DATE 1901\n2 PLAC Westford\n"
    ).replace("1 NAME John /Miller/", "1 NAME Thomas /Miller/")  # fmt: skip
    score = gold.score(wrong, gold_set)
    verdicts = _verdicts(score)
    assert verdicts[("I2", "DEAT")] == gold.WRONG and verdicts[("I2", "father")] == gold.WRONG
    assert [o.found for o in score.outcomes if o.extra] == ["1901, Westford"]
    assert score.precision() == 3 / 5 and score.recall() == 3 / 5
    assert score.calibration()["3"] == (3, 4)


@pytest.mark.parametrize(
    "found, expected, verdict",
    [
        ("3 MAR 1820", "3 MAR 1820", gold.RIGHT),
        ("MAR 1820", "3 MAR 1820", gold.VAGUE),
        ("BEF 1830", "3 MAR 1820", gold.VAGUE),
        ("4 MAR 1820", "3 MAR 1820", gold.WRONG),
        ("AFT 1830", "3 MAR 1820", gold.WRONG),
        ("", "3 MAR 1820", gold.VAGUE),
        ("1820", "", gold.RIGHT),
        ("1 APR 1738", "BET 1737 AND 1738", gold.RIGHT),
        ("1 APR 1739", "BET 1737 AND 1738", gold.WRONG),
        ("ABT 1738", "BET 1737 AND 1738", gold.VAGUE),
        ("20 JAN 1788", "BEF 21 JAN 1788", gold.RIGHT),
    ],
)
def test_date_verdicts(found, expected, verdict):
    assert gold.date_verdict(found, expected) == verdict


def _transcript(path: Path, *calls: tuple[str, dict]) -> Path:
    lines = [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": data}]}}
        for name, data in calls
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    return path


def test_lookups_of_living_persons_are_counted(gold_set, tree, tmp_path):
    log = _transcript(
        tmp_path / "round.jsonl",
        ("Bash", {"command": "lineage person I7; lineage ancestors I7"}),
        ("Write", {"file_path": "report.md", "content": "forefather of James Miller (I7)"}),
        ("WebSearch", {"query": "James Miller Northfield"}),
        ("Bash", {"command": "cd x && lineage archive search 'James Miller' | head"}),
        ("WebFetch", {"url": "https://example.org/?q=James+Miller"}),
        ("WebSearch", {"query": "William Miller 1820"}),
    )
    score = gold.score(tree, gold_set, [log])
    assert score.living == ["WebSearch I7 (round.jsonl)", "Bash I7 (round.jsonl)", "WebFetch I7 (round.jsonl)"]
    assert score.text().splitlines()[-1].endswith("3")


def test_a_parent_without_surname_matches_on_the_whole_name(gold_set, tree):
    tree = tree.replace("1 NAME Ann /Taylor/", "1 NAME Ann Cornelis Jans")
    gold_set[0].parents[1].name = "Ann Cornelis Jans"
    assert _verdicts(gold.score(tree, gold_set))[("I2", "mother")] == gold.RIGHT
    gold_set[0].parents[1].name = "Ann Pieters Jans"
    assert _verdicts(gold.score(tree, gold_set))[("I2", "mother")] == gold.WRONG
