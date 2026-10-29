import datetime as dt
import shutil

import pytest

from lineage import queue, settings
from lineage.cli import main
from lineage.gedcom import parse
from tests.conftest import FIXTURE, ged, project

TODAY = dt.date(2026, 9, 30)


def test_add_and_next(tree):
    items = {}
    queue.add(items, tree, "I2", priority=3, today=TODAY)
    queue.add(items, tree, "I4", priority=1, reason="father of I2", via="I2", today=TODAY)
    assert queue.next_open(items).id == "I4"
    assert items["I4"].added == "2026-09-30"


def test_adding_twice_keeps_the_first(tree):
    items = {}
    queue.add(items, tree, "I2", reason="first", today=TODAY)
    item, new = queue.add(items, tree, "I2", reason="second", today=TODAY)
    assert (new, item.reason) == (False, "first")


def test_unknown_person_is_rejected(tree):
    with pytest.raises(queue.QueueError):
        queue.add({}, tree, "I999", today=TODAY)


def test_possibly_living_is_skipped():
    tree = parse(
        ged(
            "0 @I1@ INDI",
            "1 BIRT",
            "2 DATE 1950",
            "0 @I2@ INDI",
            "1 BIRT",
            "2 DATE 1950",
            "1 DEAT Y",
        )
    )
    items = {}
    assert queue.add(items, tree, "I1", today=TODAY)[0].status == "skipped"
    assert queue.add(items, tree, "I2", today=TODAY)[0].status == "open"


def test_undated_person_with_old_events_or_children_is_not_living():
    tree = parse(
        ged(
            "0 @I1@ INDI",
            "1 OCCU alderman",
            "2 DATE 1597",
            "0 @I2@ INDI",
            "1 FAMS @F1@",
            "0 @I3@ INDI",
            "1 FAMC @F1@",
            "1 DEAT",
            "2 DATE BET 1601 AND 1605",
            "0 @I4@ INDI",
            "0 @F1@ FAM",
            "1 WIFE @I2@",
            "1 CHIL @I3@",
        )
    )
    items = {}
    assert queue.add(items, tree, "I1", today=TODAY)[0].status == "open"
    assert queue.add(items, tree, "I2", today=TODAY)[0].status == "open"
    assert queue.add(items, tree, "I4", today=TODAY)[0].status == "skipped"


def test_start_assigns_distinct_id_blocks(tree):
    items = {}
    for pid in ("I2", "I6"):
        queue.add(items, tree, pid, today=TODAY)
    first = queue.start(items, tree, "I2")
    second = queue.start(items, tree, "I6")
    assert first.id_block == "800001-800999"
    assert second.id_block == "801001-801999"
    assert first.status == second.status == "in_progress"
    with pytest.raises(queue.QueueError):
        queue.start(items, tree, "I2")


def test_start_skips_blocks_used_in_the_tree():
    tree = parse(ged("0 @I1@ INDI", "1 DEAT Y", "0 @I800005@ INDI"))
    items = {}
    queue.add(items, tree, "I1", today=TODAY)
    assert queue.start(items, tree, "I1").id_block == "801001-801999"


def test_start_skips_blocks_used_only_by_sources():
    # A follow-up round replaces the item's id_block, so its earlier block is only visible in the tree.
    tree = parse(ged("0 @I1@ INDI", "1 DEAT Y", "0 @S800001@ SOUR"))
    items = {}
    queue.add(items, tree, "I1", today=TODAY)
    assert queue.start(items, tree, "I1").id_block == "801001-801999"


def test_union_merge_duplicates_keep_most_advanced_status(tmp_path, tree):
    path = tmp_path / "queue.tsv"
    items = {}
    queue.add(items, tree, "I2", today=TODAY)
    queue.start(items, tree, "I2")
    queue.save(items, path)
    header, line = path.read_text().splitlines()
    open_line = line.replace("\tin_progress\t", "\topen\t").replace("800001-800999", "")
    done_line = line.replace("\tin_progress\t", "\tdone\t") + "reports/persons/I2.md"
    path.write_text("\n".join([header, open_line, done_line, line]) + "\n")
    merged = queue.load(path)
    assert merged["I2"].status == "done"
    assert merged["I2"].id_block == "800001-800999"
    queue.save(merged, path)
    assert len(path.read_text().splitlines()) == 2


def test_follow_up_round_gets_a_new_block_and_survives_merge(tmp_path, tree):
    path = tmp_path / "queue.tsv"
    items = {}
    queue.add(items, tree, "I2", today=TODAY)
    queue.start(items, tree, "I2")
    queue.finish(items, "I2", "reports/persons/I2.md")
    with pytest.raises(queue.QueueError):
        queue.start(items, tree, "I2")
    queue.save(items, path)
    old_line = path.read_text().splitlines()[1]
    follow_up = queue.start(items, tree, "I2", follow_up=True)
    assert follow_up.status == "in_progress"
    assert follow_up.id_block == "801001-801999"
    queue.save(items, path)
    header, new_line = path.read_text().splitlines()
    path.write_text("\n".join([header, new_line, old_line]) + "\n")
    merged = queue.load(path)
    assert merged["I2"].status == "in_progress"
    assert merged["I2"].id_block == "801001-801999"


def test_cli_flow(tmp_path, capsys):
    project(tmp_path, line_root="I1")
    q = tmp_path / "w.tsv"
    ged_file = tmp_path / "family.ged"
    shutil.copy(FIXTURE, ged_file)
    base = ["--file", str(ged_file), "queue", "--queue", str(q)]
    assert main([*base, "add", "I2", "I7", "--reason", "test"]) == 0
    assert main([*base, "next"]) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == "I2"
    assert main([*base, "start", "I2"]) == 0
    assert (
        main(
            [*base, "done", "I2", "--report", "reports/persons/I2.md", "--date", "2026-09-30"]
        )
        == 0
    )
    assert "1 NOTE Deep research 30-09-2026: reports/persons/I2.md" in ged_file.read_text()
    assert main([*base, "start", "I2"]) == 2
    assert main([*base, "start", "I2", "--follow-up"]) == 0
    assert (
        main([*base, "done", "I2", "--report", "r.md", "--date", "2026-10-01", "--no-note"])
        == 0
    )
    assert "Deep research 01-10-2026" not in ged_file.read_text()
    assert "Deep research 30-09-2026" in ged_file.read_text()
    main([*base, "show", "--all"])
    out = capsys.readouterr().out
    assert "done" in out and "1 done" in out


def test_start_refuses_family_member_of_running_research(tree):
    items = {}
    for pid in ("I1", "I2", "I6"):
        queue.add(items, tree, pid, today=TODAY)
    queue.start(items, tree, "I2")
    with pytest.raises(queue.QueueError, match="I2"):
        queue.start(items, tree, "I1")
    assert queue.next_open(items, tree).id == "I6"
    assert queue.start(items, tree, "I1", force=True).status == "in_progress"


def test_next_open_within_the_direct_line(tree):
    items = {}
    queue.add(items, tree, "I6", priority=1, today=TODAY)
    queue.add(items, tree, "I4", priority=5, today=TODAY)
    assert queue.direct_line(tree, "I1") == {"I1", "I2", "I3", "I4", "I5"}
    assert queue.next_open(items, tree).id == "I6"
    assert queue.next_open(items, tree, queue.direct_line(tree, "I1")).id == "I4"


def test_direct_line_defaults_to_the_project(tree, tmp_path):
    project(tmp_path, targets=(settings.Target("Me", "I2"),))
    assert queue.direct_line(tree) == {"I2", "I4", "I5"}
    project(tmp_path, targets=(settings.Target("Me", "I2"),), line_root="I1")
    assert "I1" in queue.direct_line(tree)
    project(tmp_path)
    with pytest.raises(settings.ConfigError, match="line_root"):
        queue.direct_line(tree)


def test_cli_parks_side_branches(tmp_path, capsys):
    project(tmp_path, line_root="I1")
    q = tmp_path / "w.tsv"
    base = ["--file", str(FIXTURE), "queue", "--queue", str(q)]
    main([*base, "add", "I6", "--reason", "side branch"])
    capsys.readouterr()
    assert main([*base, "next"]) == 1
    assert main([*base, "next", "--side-branches"]) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == "I6"
    main([*base, "show"])
    out = capsys.readouterr().out
    assert "Smith" not in out and "1 open in side branches" in out
    main([*base, "show", "--side-branches"])
    assert "Smith" in capsys.readouterr().out


def test_next_open_puts_the_paternal_lines_first(tmp_path):
    from lineage.gedcom import parse
    from tests.conftest import ged

    tree = parse(ged(
        "0 @I1@ INDI", "1 NAME Child /D/", "1 SEX M", "1 FAMC @F1@",
        "0 @I2@ INDI", "1 NAME Father /D/", "1 SEX M", "1 FAMS @F1@", "1 FAMC @F2@",
        "0 @I3@ INDI", "1 NAME Mother /E/", "1 SEX F", "1 FAMS @F1@", "1 FAMC @F3@",
        "0 @I4@ INDI", "1 NAME Grandpa /D/", "1 SEX M", "1 FAMS @F2@",
        "0 @I5@ INDI", "1 NAME Grandma /X/", "1 SEX F", "1 FAMS @F2@",
        "0 @I6@ INDI", "1 NAME Grandpa /E/", "1 SEX M", "1 FAMS @F3@",
        "0 @F1@ FAM", "1 HUSB @I2@", "1 WIFE @I3@", "1 CHIL @I1@",
        "0 @F2@ FAM", "1 HUSB @I4@", "1 WIFE @I5@", "1 CHIL @I2@",
        "0 @F3@ FAM", "1 HUSB @I6@", "1 CHIL @I3@",
    ))  # fmt: skip
    items = {
        "I6": queue.Item("I6", "open", priority=1, round=1),
        "I5": queue.Item("I5", "open", priority=5, round=4),
    }
    stems = (("D", "I1"), ("E", "I3"))
    assert queue.stem_rank(tree, stems) == {"I1": 0, "I2": 0, "I3": 0, "I4": 0, "I5": 0, "I6": 1}
    project(tmp_path, stems=(settings.Stem("D", "I1"), settings.Stem("E", "I3")))
    assert queue.next_open(items, tree).id == "I5"
    assert queue.next_open(items).id == "I6"
    items["I7"] = queue.Item("I7", "open", priority=queue.USER_PICK, round=6)
    assert queue.next_open(items, tree, line={"I1"}).id == "I7"


def test_stem_rank_men_first():
    from tests.conftest import ged

    tree = parse(ged(
        "0 @I1@ INDI", "1 NAME Child /D/", "1 SEX M", "1 FAMC @F1@",
        "0 @I2@ INDI", "1 NAME Father /D/", "1 SEX M", "1 FAMS @F1@",
        "0 @I3@ INDI", "1 NAME Mother /M/", "1 SEX F", "1 FAMS @F1@",
        "0 @F1@ FAM", "1 HUSB @I2@", "1 WIFE @I3@", "1 CHIL @I1@",
    ))  # fmt: skip
    assert queue.stem_rank(tree, (("D", "I1", "men-first"),)) == {"I1": 0, "I2": 0, "I3": 0.5}
    items = {
        "I3": queue.Item("I3", "open", priority=1, round=1),
        "I2": queue.Item("I2", "open", priority=5, round=4),
    }
    assert queue.next_open(items, tree, stems=(("D", "I1", "men-first"),)).id == "I2"
    assert queue.next_open(items, tree, stems=(("D", "I1"),)).id == "I3"


def test_next_open_takes_paternal_line_wives_outside_the_direct_line():
    from tests.conftest import ged

    tree = parse(ged(
        "0 @I1@ INDI", "1 NAME Child /D/", "1 SEX M", "1 FAMC @F1@",
        "0 @I2@ INDI", "1 NAME Father /D/", "1 SEX M", "1 FAMS @F1@", "1 FAMS @F2@",
        "0 @I3@ INDI", "1 NAME Mother /M/", "1 SEX F", "1 FAMS @F1@", "1 FAMC @F3@",
        "0 @I4@ INDI", "1 NAME Second /V/", "1 SEX F", "1 FAMS @F2@",
        "0 @I5@ INDI", "1 NAME Grandpa /M/", "1 SEX M", "1 FAMS @F3@",
        "0 @F1@ FAM", "1 HUSB @I2@", "1 WIFE @I3@", "1 CHIL @I1@",
        "0 @F2@ FAM", "1 HUSB @I2@", "1 WIFE @I4@",
        "0 @F3@ FAM", "1 HUSB @I5@", "1 CHIL @I3@",
    ))  # fmt: skip
    items = {
        "I5": queue.Item("I5", "open", priority=1, round=1),
        "I4": queue.Item("I4", "open", priority=5, round=4),
    }
    assert "I4" not in queue.direct_line(tree, "I1")
    assert queue.next_open(items, tree, queue.direct_line(tree, "I1"), (("D", "I1"),)).id == "I4"


def test_load_accepts_the_dutch_header_and_statuses(tmp_path):
    path = tmp_path / "queue.tsv"
    path.write_text(
        "id\tstatus\tprioriteit\tronde\tdoor\treden\ttoegevoegd\tidreeks\trapport\n"
        "I2\tbezig\t3\t2\tI4\tfather\t2026-09-30\t800001-800999\t\n"
        "I4\tklaar\t1\t1\t\t\t2026-09-30\t801001-801999\treports/persons/I4.md\n"
        "I6\tovergeslagen\t5\t1\t\tpossibly living\t2026-09-30\t\t\n",
        encoding="utf-8",
    )
    items = queue.load(path)
    assert items["I2"] == queue.Item(
        "I2", "in_progress", 3, 2, "I4", "father", "2026-09-30", "800001-800999", ""
    )
    assert items["I4"].status == "done" and items["I4"].report == "reports/persons/I4.md"
    assert items["I6"].status == "skipped"
    queue.save(items, path)
    header, *_ = path.read_text(encoding="utf-8").splitlines()
    assert header == "\t".join(queue.FIELDS)
    assert queue.load(path) == items


def test_errors_are_dutch_in_a_dutch_project(tree, tmp_path):
    project(tmp_path, language="nl")
    with pytest.raises(queue.QueueError, match="staat niet in de wachtrij"):
        queue.start({}, tree, "I1")
