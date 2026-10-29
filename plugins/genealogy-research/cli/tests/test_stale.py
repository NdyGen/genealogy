import datetime as dt
import subprocess
import time
from pathlib import Path

from lineage import stale
from lineage.gedcom import load, parse
from tests.conftest import ged, project

GED = ged(
    "0 @I1@ INDI",
    "1 NAME Peter /Hart/",
    "1 SEX M",
    "1 FAMS @F1@",
    "0 @I2@ INDI",
    "1 NAME Anna /Cole/",
    "1 SEX F",
    "1 FAMS @F1@",
    "0 @I3@ INDI",
    "1 NAME John /Hart/",
    "1 SEX M",
    "1 FAMC @F1@",
    "0 @F1@ FAM",
    "1 HUSB @I1@",
    "1 WIFE @I2@",
    "1 CHIL @I3@",
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "HOME": str(root),
            "PATH": "/usr/bin:/bin",
        },
    )


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    (root / "reports/life-stories").mkdir(parents=True)
    _git(root, "init", "-q")
    (root / "data/tree.ged").write_text(GED + "\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "tree")
    (root / "reports/life-stories/I1.md").write_text("# Peter\n", encoding="utf-8")
    (root / "reports/life-stories/I2.md").write_text("# Anna\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "stories I1 and I2")
    return root


def test_related_records_cover_marriages_and_children():
    tree = parse(GED)
    assert stale.related_records(tree, "I1") == ["I1", "F1", "I3"]
    assert stale.related_records(tree, "I3") == ["I3"]


def test_direct_line_also_covers_the_parents_family():
    tree = parse(GED)
    assert stale.related_records(tree, "I3", direct_line={"I3", "I1"}) == ["I3", "F1", "I1", "I2"]
    assert stale.related_records(tree, "I3", direct_line={"I1"}) == ["I3"]


def test_story_newer_than_record_is_not_stale(tmp_path):
    root = _repo(tmp_path)
    tree = load(root / "data/tree.ged")
    assert stale.stale_stories(tree, root) == []


def test_record_change_after_story_makes_it_stale_including_family(tmp_path):
    root = _repo(tmp_path)
    time.sleep(1.1)  # commit times have second resolution
    ged_path = root / "data/tree.ged"
    ged_path.write_text(
        ged_path.read_text(encoding="utf-8").replace(
            "1 CHIL @I3@", "1 CHIL @I3@\n1 MARR\n2 DATE 1920"
        ),
        encoding="utf-8",
    )
    _git(root, "commit", "-qam", "F1: marriage 1920 (record 7)")
    tree = load(ged_path)
    stale_items = stale.stale_stories(tree, root)
    assert sorted(s.pid for s in stale_items) == ["I1", "I2"]
    assert stale_items[0].records == ["F1"] and stale_items[0].summaries == [
        "F1: marriage 1920 (record 7)"
    ]
    assert "2 life stories to update" in stale.report(tree, stale_items)
    assert stale.report(tree, stale_items, short=True).splitlines() == [s.pid for s in stale_items]


def test_research_note_does_not_count_as_change(tmp_path):
    root = _repo(tmp_path)
    time.sleep(1.1)
    ged_path = root / "data/tree.ged"
    ged_path.write_text(
        ged_path.read_text(encoding="utf-8").replace(
            "1 FAMS @F1@\n0 @I2@", "1 FAMS @F1@\n1 NOTE Deep research 01-10-2026: r.md\n0 @I2@"
        ),
        encoding="utf-8",
    )
    _git(root, "commit", "-qam", "Deep research I1 merged")
    tree = load(ged_path)
    assert stale.stale_stories(tree, root) == []


def test_cache_is_reused_until_the_gedcom_changes(tmp_path):
    root = _repo(tmp_path)
    first = stale.record_changes(root)
    assert stale._cache_path(root).exists()
    assert stale.record_changes(root) == first


def test_a_check_without_changes_counts_as_the_story_date(tmp_path):
    root = _repo(tmp_path)
    time.sleep(1.1)
    ged_path = root / "data/tree.ged"
    ged_path.write_text(
        ged_path.read_text(encoding="utf-8").replace("1 SEX F", "1 SEX F\n1 OCCU seamstress"),
        encoding="utf-8",
    )
    _git(root, "commit", "-qam", "I2: occupation")
    tree = load(ged_path)
    assert [s.pid for s in stale.stale_stories(tree, root)] == ["I2"]
    stale.mark_checked(root, "I2", dt.datetime.now().astimezone() + dt.timedelta(seconds=5))
    assert stale.stale_stories(tree, root) == []
    assert (root / "research/stories-checked.tsv").read_text(encoding="utf-8").startswith("I2\t")


def test_rewrapping_a_note_with_conc_does_not_count(tmp_path):
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    (root / "reports/life-stories").mkdir(parents=True)
    _git(root, "init", "-q")
    ged_path = root / "data/tree.ged"
    ged_path.write_text(
        GED.replace("1 SEX M\n1 FAMS", "1 SEX M\n1 NOTE a long note about Peter\n1 FAMS", 1) + "\n",
        encoding="utf-8",
    )
    (root / "reports/life-stories/I1.md").write_text("# Peter\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "tree and story")
    time.sleep(1.1)
    ged_path.write_text(
        ged_path.read_text(encoding="utf-8").replace(
            "1 NOTE a long note about Peter", "1 NOTE a long no\n2 CONC te about Peter"
        ),
        encoding="utf-8",
    )
    _git(root, "commit", "-qam", "long NOTE line split")
    tree = load(ged_path)
    assert stale.stale_stories(tree, root) == []


def test_report_in_dutch(tmp_path):
    project(tmp_path, language="nl")
    tree = parse(GED)
    item = stale.Stale("I1", 0, 86400, ["F1"], ["F1: huwelijk"])
    text = stale.report(tree, [item])
    assert "verhaal " in text and "record gewijzigd " in text
    assert text.endswith("1 levensverhalen bij te werken")
